from datetime import datetime, timedelta, timezone

import signal_reels as sr

MASK = "$MASK -> LONG\nТочка входа: 0.3743\nТаргеты: 0.3781, 0.3820, 0.4039\nСтоп: 0.3605\nВыделил: 1200$"
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


def page(*posts):
    return "".join(
        f'<div class="tgme_widget_message js-widget_message" data-post="Apex_Trader_Uz/{i}" data-view="x">'
        f'<div class="tgme_widget_message_text js-message_text" dir="auto">{t}</div>'
        f'<a class="tgme_widget_message_date"><time datetime="{ts.isoformat()}" class="time">12:00</time></a></div>'
        for i, t, ts in posts)


def test_parse_signal_and_bad_ones():
    s = sr.parse_signal(MASK)
    assert s["symbol"] == "MASKUSDT" and s["targets"] == [0.3781, 0.382, 0.4039]
    assert sr.parse_signal("Bugun bozor yaxshi, LONG foydada") is None
    assert sr.parse_signal(MASK.replace("0.3605", "0.40")) is None  # stop entry'dan yuqori


def test_parse_channel_html_handles_br_and_entities():
    msgs = sr.parse_channel_html(page((7, MASK.replace("\n", "<br/>").replace(">", "&gt;"), NOW)))
    assert msgs[0]["id"] == 7 and sr.parse_signal(msgs[0]["text"])["side"] == "LONG"


def msg(i, text, age_h=0.5, reply_to=None):
    return {"id": i, "text": text, "time": NOW - timedelta(hours=age_h), "reply_to": reply_to}


def test_pick_newest_signal_and_marks_news_seen():
    state = {"seen": [], "posts": [], "promo_day": ""}
    m, sig = sr.pick_signal([msg(1, "yangilik"), msg(2, MASK), msg(3, MASK.replace("MASK", "BTC"))], state, NOW)
    assert m["id"] == 3 and sig["symbol"] == "BTCUSDT"
    assert 1 in state["seen"] and 3 in state["seen"] and 2 not in state["seen"]  # 2 keyingi safar chiqadi


def test_old_signals_and_limits():
    state = {"seen": [], "posts": [], "promo_day": ""}
    assert sr.pick_signal([msg(1, MASK, age_h=9)], state, NOW) is None and 1 in state["seen"]
    state = {"seen": [], "posts": [{"time": (NOW - timedelta(minutes=20)).isoformat(), "kind": "signal"}], "promo_day": ""}
    assert sr.pick_signal([msg(5, MASK)], state, NOW) is None and 5 not in state["seen"]  # oraliq tugaguncha kutadi
    full = [{"time": (NOW - timedelta(hours=h)).isoformat(), "kind": "signal"} for h in (2, 4, 6)]
    assert sr.pick_signal([msg(6, MASK)], {"seen": [], "posts": full, "promo_day": ""}, NOW) is None


def test_caption_has_disclaimer_and_no_promises():
    c = sr.caption_for(sr.parse_signal(MASK))
    assert "moliyaviy maslahat emas" in c and "kafolat" not in c.lower() and "t.me/Apex_Trader_Uz" in c


JTO = "📈 JTO LONG плечо x25\n\nТочка входа: рынок (0.3388)\n\nТаргет 1: 0.3423\nТаргет 2: 0.3474\nТаргет 3: 0.3620\n\nСтоп: 0.3202\n\nМоя маржа: 700$\nБанк марафона: 7545.14$"


def test_market_entry_numbered_targets_format():
    s = sr.parse_signal(JTO)
    assert s == {"symbol": "JTOUSDT", "side": "LONG", "entry": 0.3388, "stop": 0.3202, "targets": [0.3423, 0.3474, 0.362]}
    assert sr.parse_signal("Открыл сделку в лонг с 20 плечом по GRASS и JTO") is None


def test_parse_result_profit_only():
    assert sr.parse_result("JTO: взят тейк 2 ✅ +51% с плечом") == {"outcome": "profit", "target": 2, "pct": "+51%"}
    assert sr.parse_result("Первый таргет достигнут")["target"] == 1
    assert sr.parse_result("Закрыл в плюс, профит зафиксирован") == {"outcome": "profit", "target": None, "pct": None}
    assert sr.parse_result("Всем привет") is None and sr.parse_result(JTO) is None


def tracked():
    return {"seen": [], "posts": [], "promo_day": "", "signals": {"189": {"sig": sr.parse_signal(JTO), "media_id": "1", "results": []}}}


def test_result_matched_by_reply_or_ticker_and_not_repeated():
    st = tracked()
    m, key, res = sr.find_result([msg(200, "Тейк 1 взят ✅", reply_to=189)], st)
    assert (key, res["target"]) == ("189", 1)
    st["signals"]["189"]["results"].append(1)
    assert sr.find_result([msg(200, "Тейк 1 взят ✅", reply_to=189)], st) is None and 200 in st["seen"]
    m, key, res = sr.find_result([msg(201, "JTO таргет 2 достигнут")], tracked())
    assert key == "189" and res["target"] == 2
    assert sr.find_result([msg(202, "ETH тейк 1 взят")], tracked()) is None  # kuzatilmagan ticker


def test_result_message_is_held_while_signal_posts():
    st = tracked()
    msgs = [msg(210, "Тейк 1 взят ✅", reply_to=189), msg(211, MASK)]
    res = sr.find_result(msgs, st)
    choice = sr.pick_signal(msgs, st, NOW, frozenset({res[0]["id"]}))
    assert choice[0]["id"] == 211 and 210 not in st["seen"]


def test_reply_id_parsed_from_html():
    html_ = ('<div class="tgme_widget_message" data-post="Apex_Trader_Uz/9"><a class="tgme_widget_message_reply user-select" '
             'href="https://t.me/Apex_Trader_Uz/189"><div class="tgme_widget_message_metatext js-message_reply_text">x</div></a>'
             f'<div class="tgme_widget_message_text js-message_text" dir="auto">Тейк 1 взят</div><time datetime="{NOW.isoformat()}"></time></div>')
    assert sr.parse_channel_html(html_)[0]["reply_to"] == 189


def test_result_caption_is_unleveraged_and_balanced():
    c = sr.result_caption(sr.parse_signal(JTO), {"outcome": "profit", "target": 1, "pct": "+25%"})
    assert "+1.0%" in c and "leveragesiz" in c and "zarar bilan yopilgan" in c and "+25%" not in c


def test_chatter_is_not_a_result():
    for text in ["Начали день сразу со сделки, так как открытых позиций у нас не было. Кто заходит со мной? Отмечаемся 🔥",
                 "Хорошей прибыли всем, идем к цели ✅", "Сегодня будем в плюсе", "Ставим тейк и ждем таргет"]:
        assert sr.parse_result(text) is None, text


def test_stop_results_are_detected_and_reported():
    for text in ["Выбило по стопу -5% ❌", "JTO: стоп сработал", "Закрыл сделку в минус", "Словили стоп, убыток небольшой", "Сделка закрыта, небольшой убыток"]:
        assert sr.parse_result(text) == {"outcome": "loss", "target": None, "pct": None}, text
    for text in ["Ставим стоп в безубыток", "Не забывайте про стоп-лосс", "Стоп переносим выше"]:
        assert sr.parse_result(text) is None, text
    c = sr.result_caption(sr.parse_signal(JTO), {"outcome": "loss", "target": None, "pct": None})
    assert "Stop-loss ishladi" in c and "-5.5%" in c and "leveragesiz" in c


def test_loss_closes_signal_and_is_not_repeated():
    st = tracked()
    m, key, res = sr.find_result([msg(300, "Выбило по стопу", reply_to=189)], st)
    assert res["outcome"] == "loss" and sr.result_mark(res) == -1
    st["signals"]["189"]["results"].append(-1)
    assert sr.find_result([msg(301, "Тейк 1 взят ✅", reply_to=189)], st) is None  # stopdan keyin boshqa natija yo'q
