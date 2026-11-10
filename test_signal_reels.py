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


def msg(i, text, age_h=0.5):
    return {"id": i, "text": text, "time": NOW - timedelta(hours=age_h)}


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
