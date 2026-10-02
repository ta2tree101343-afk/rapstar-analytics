from collector.classifier import classify_caption


ENTRY_SAMPLE = (
    "imag1ne / 22 / 東京\n"
    "RAPSTAR 2026\n"
    "\n"
    "12,953人の中から厳選された\n"
    "応募動画を先行公開\n"
    "\n"
    "#RAPSTAR #RAPSTAR2026 #ラップスタア"
)


def test_entry_hashtag_yields_entry():
    r = classify_caption(ENTRY_SAMPLE)
    assert r.status == "entry"
    assert r.rapper_name == "imag1ne"


def test_hashtag_is_case_insensitive():
    r = classify_caption("Something\n#rapstar2026")
    assert r.status == "entry"


def test_missing_hashtag_is_unclassified():
    r = classify_caption("番組告知です #RAPSTAR")
    assert r.status == "unclassified"


def test_none_caption_returns_unclassified_no_name():
    r = classify_caption(None)
    assert r.status == "unclassified"
    assert r.rapper_name is None


def test_empty_caption_returns_unclassified_no_name():
    r = classify_caption("")
    assert r.status == "unclassified"
    assert r.rapper_name is None


def test_rapper_name_first_slash_token():
    r = classify_caption("Kee Rooz / 25 / 大阪\n#RAPSTAR2026")
    assert r.rapper_name == "Kee Rooz"


def test_rapper_name_without_slash():
    r = classify_caption("BabyNyca\n#RAPSTAR2026")
    assert r.rapper_name == "BabyNyca"
