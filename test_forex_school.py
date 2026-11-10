import json

import forex_school as fs

LESSONS = json.load(open("content/lessons.json", encoding="utf-8"))


def test_every_lesson_fits_caption_and_keeps_risk_note():
    for i, lesson in enumerate(LESSONS):
        cap = fs.caption(lesson, i + 1, len(LESSONS))
        assert len(cap) <= 1024 and "moliyaviy maslahat emas" in cap and "{LINK}" not in cap


def test_quiz_correct_answer_survives_shuffle():
    for i, lesson in enumerate(LESSONS):
        if "quiz" in lesson:
            p = fs.quiz_payload(lesson["quiz"], i)
            assert json.loads(p["options"])[p["correct_option_id"]] == lesson["quiz"]["options"][0]
            assert len(p["question"]) <= 300 and len(set(json.loads(p["options"]))) == 4


def test_buttons_keep_affiliate_and_channel_invite():
    kb = json.loads(fs.keyboard())["inline_keyboard"]
    assert kb[0][0]["url"] == fs.AFFILIATE and "hamkorlik" in kb[0][0]["text"]
    assert kb[1][0]["url"] == "https://t.me/Apex_Trader_Uz"


def test_card_renders(tmp_path):
    out = tmp_path / "c.jpg"
    fs.make_card(LESSONS[7], 8, 20, str(out))
    assert out.stat().st_size > 20000
