import unittest

from attention_board import build_attention_days, build_attention_mk


class AttentionBoardTests(unittest.TestCase):
    def test_topic_moves_from_new_to_rotation_to_ladder_and_keeps_its_trace(self):
        dates = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
        rows = {
            dates[0]: [{"code": "000001", "name": "S1", "tags": ["T1"], "level": 1, "first_time": 100000}],
            dates[1]: [{"code": "000002", "name": "S2", "tags": ["T1"], "level": 1, "first_time": 94000}],
            dates[2]: [{"code": "000002", "name": "S2", "tags": ["T1"], "level": 2, "first_time": 93100}],
            dates[3]: [{"code": "000003", "name": "S3", "tags": ["T1"], "level": 1, "first_time": 94500}],
        }
        boards = build_attention_days(dates, rows)
        self.assertEqual([next((k for k in ("al", "an", "ar") if b[k]), "") for b in boards],
                         ["al", "al", "ar", "an"])
        latest = boards[0]["al"][0]
        self.assertEqual([s["name"] for s in latest["stocks"]], ["S3", "S2", "S1"])
        self.assertEqual([s["break_days"] for s in latest["stocks"]], [0, 1, 3])

    def test_same_board_earlier_first_seal_is_stronger_and_topics_are_exclusive(self):
        day = "2026-09-30"
        rows = {day: [
            {"code": "000001", "name": "Late", "tags": ["T1"], "level": 3, "first_time": 103000},
            {"code": "000002", "name": "Early", "tags": ["T1", "T2"], "level": 3, "first_time": 93300},
            {"code": "000003", "name": "First", "tags": ["T1"], "level": 1, "first_time": 93000},
        ]}
        board = build_attention_days([day], rows)[0]
        self.assertEqual([t["theme"] for t in board["al"]], ["T1", "T2"])
        self.assertEqual([s["name"] for s in board["al"][0]["stocks"]], ["Early", "Late", "First"])
        self.assertEqual(board["an"], [])
        self.assertEqual(board["ar"], [])

    def test_history_is_bounded_to_supplied_dates(self):
        dates = ["2026-09-29", "2026-09-30"]
        rows = {
            "2026-09-28": [{"code": "000001", "tags": ["T1"], "level": 4}],
            dates[0]: [{"code": "000002", "tags": ["T2"], "level": 1}],
            dates[1]: [{"code": "000003", "tags": ["T2"], "level": 1}],
        }
        boards = build_attention_days(dates, rows)
        self.assertEqual(boards[0]["al"], [])
        self.assertEqual([t["theme"] for t in boards[0]["ar"]], ["T2"])
        self.assertEqual([t["theme"] for t in boards[1]["an"]], ["T2"])

    def test_restarted_lower_streak_keeps_current_layer_and_marks_previous_peak(self):
        dates = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
        rows = {
            dates[0]: [{"code": "000001", "name": "回流股", "tags": ["T1"], "level": 3}],
            dates[3]: [{"code": "000001", "name": "回流股", "tags": ["T1"], "level": 2}],
        }
        latest = build_attention_days(dates, rows)[0]["al"][0]["stocks"][0]
        self.assertEqual(latest["display_level"], 2)
        self.assertEqual(latest["prior_peak_level"], 3)
        self.assertFalse(latest["is_break1"])

    def test_first_board_break_one_day_is_retained_but_stale_first_board_is_hidden(self):
        dates = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
        rows = {
            dates[2]: [{"code": "000001", "name": "首板断板", "tags": ["T1"], "level": 1}],
            dates[3]: [{"code": "000002", "name": "今日首板", "tags": ["T1"], "level": 1}],
        }
        topic = build_attention_days(dates, rows)[0]["ar"][0]
        broken = next(stock for stock in topic["stocks"] if stock["code"] == "000001")
        self.assertTrue(broken["is_break1"])
        self.assertEqual(broken["display_level"], 0)

        stale_only = build_attention_days(dates, {
            dates[0]: [{"code": "000003", "name": "过期首板", "tags": ["T2"], "level": 1}],
        })[0]
        self.assertFalse(any(stale_only[k] for k in ("al", "an", "ar")))

    def test_large_gain_enters_first_column_then_moves_to_break_trace(self):
        dates = ["2026-09-25", "2026-09-28", "2026-09-29"]
        rows = {
            dates[0]: [{"code": "300001", "name": "大涨股", "tags": ["新题材"],
                        "level": 0, "event_type": "big_gain", "change_pct": 12.3, "board": "创"}],
            dates[1]: [{"code": "000001", "name": "同题材首板", "tags": ["新题材"], "level": 1}],
            dates[2]: [{"code": "000002", "name": "同题材助攻", "tags": ["新题材"], "level": 1}],
        }
        boards = build_attention_days(dates, rows)
        first_day = boards[2]["an"][0]["stocks"][0]
        self.assertEqual(first_day["status"], "big_gain")
        self.assertTrue(first_day["is_big_gain"])
        self.assertEqual(first_day["display_level"], 1)
        self.assertEqual(first_day["board"], "创")

        next_topic = next(t for group in (boards[1]["al"], boards[1]["an"], boards[1]["ar"])
                          for t in group if t["theme"] == "新题材")
        next_day = next(stock for stock in next_topic["stocks"] if stock["code"] == "300001")
        self.assertEqual(next_day["status"], "broken")
        self.assertFalse(next_day["is_break1"])
        self.assertTrue(next_day["is_break_n"])
        self.assertEqual(next_day["break_days"], 1)

        later_topic = next(t for group in (boards[0]["al"], boards[0]["an"], boards[0]["ar"])
                           for t in group if t["theme"] == "新题材")
        later = next(stock for stock in later_topic["stocks"] if stock["code"] == "300001")
        self.assertTrue(later["is_break_n"])
        self.assertEqual(later["break_days"], 2)

    def test_topic_without_current_limit_or_big_gain_is_hidden(self):
        dates = ["2026-09-25", "2026-09-28"]
        rows = {
            dates[0]: [{"code": "300001", "name": "昨日大涨", "tags": ["孤立题材"],
                        "level": 0, "event_type": "big_gain", "change_pct": 11.2, "board": "创"}],
        }
        today = build_attention_days(dates, rows)[0]
        self.assertFalse(any(today[k] for k in ("al", "an", "ar")))

    def test_large_gain_with_exact_existing_al_keyword_attaches_to_al(self):
        dates = ["2026-09-29", "2026-09-30"]
        rows = {
            dates[0]: [{"code": "300001", "name": "连板股", "tags": ["AI应用"], "level": 2}],
            dates[1]: [{"code": "300002", "name": "大涨股", "tags": ["AI应用"],
                        "level": 0, "event_type": "big_gain", "change_pct": 10.8, "board": "创"}],
        }
        board = build_attention_days(dates, rows)[0]
        self.assertEqual([topic["theme"] for topic in board["al"]], ["AI应用"])
        gain = next(stock for stock in board["al"][0]["stocks"] if stock["code"] == "300002")
        self.assertTrue(gain["is_big_gain"])
        self.assertEqual(gain["display_level"], 1)

    def test_strength_ranks_follow_board_then_first_board_then_nearest_break(self):
        dates = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
        rows = {
            dates[0]: [
                {"code": "000004", "name": "远期断板", "tags": ["T"], "level": 1, "first_time": 93000},
            ],
            dates[1]: [
                {"code": "000005", "name": "近期开板", "tags": ["T"], "level": 1, "first_time": 93100},
            ],
            dates[3]: [
                {"code": "000001", "name": "最高板", "tags": ["T"], "level": 3, "first_time": 101000},
                {"code": "000002", "name": "低一板早封", "tags": ["T"], "level": 2, "first_time": 93000},
                {"code": "000003", "name": "今日首板", "tags": ["T"], "level": 1, "first_time": 92500},
            ],
        }
        topic = build_attention_days(dates, rows)[0]["al"][0]
        ranks = {stock["name"]: stock["strength_rank"] for stock in topic["stocks"]}
        self.assertEqual(ranks, {
            "最高板": 1,
            "低一板早封": 2,
            "今日首板": 3,
            "近期开板": 4,
            "远期断板": 5,
        })

    def test_guidance_distinguishes_first_two_board_and_high_board_topics(self):
        dates = ["2026-09-29", "2026-09-30"]
        rows = {
            dates[0]: [
                {"code": "000001", "name": "连板核心", "tags": ["首次2板"], "level": 1},
            ],
            dates[1]: [
                {"code": "000001", "name": "连板核心", "tags": ["首次2板"], "level": 2},
                {"code": "000002", "name": "高位核心", "tags": ["高位题材"], "level": 4},
            ],
        }
        topics = {topic["theme"]: topic for category in ("al", "an", "ar")
                  for topic in build_attention_days(dates, rows)[0][category]}
        self.assertIn("首次晋级2板", topics["首次2板"]["guidance"])
        self.assertIn("N字回流", topics["首次2板"]["guidance"])
        self.assertIn("首板补涨", topics["高位题材"]["guidance"])

    def test_mk_matches_union_of_openred_tags_and_excludes_displayed_stocks(self):
        board = {
            "date": "2026-09-30",
            "al": [{"theme": "T1", "stocks": [{"code": "000001"}]}],
            "an": [{"theme": "T2", "stocks": [{"code": "000002"}]}],
            "ar": [{"theme": "T3", "stocks": [{"code": "000001"}]}],
        }
        reverse = {
            "300003": {"name": "三词交集", "concepts": [], "tags": ["T1", "T2", "T3"]},
            "688004": {"name": "两词乙", "concepts": [], "tags": ["T1", "T2"]},
            "600005": {"name": "两词甲", "concepts": [], "tags": ["T1", "T3"]},
            "000001": {"name": "已在AL", "concepts": [], "tags": ["T1", "T2", "T3"]},
            "000002": {"name": "已在AN", "concepts": [], "tags": ["T1", "T2"]},
            "000006": {"name": "行业概念不参与", "concepts": ["T1", "T2", "T3"], "tags": ["其他"]},
            "000007": {"name": "单关键词", "concepts": [], "tags": ["T2"]},
        }

        result = build_attention_mk(board, reverse, "2026-09-30")
        self.assertEqual(result["keywords"], ["T1", "T2", "T3"])
        self.assertEqual([row["name"] for row in result["matches"]], ["三词交集", "两词乙", "两词甲"])
        self.assertEqual(result["matches"][0]["matched_keywords"], ["T1", "T2", "T3"])
        self.assertEqual(result["matches"][0]["board"], "创")
        self.assertEqual(result["source_as_of"], "2026-09-30")

    def test_mk_collapses_related_theme_labels_and_filters_stocks(self):
        board = {
            "date": "2026-09-30",
            "al": [{"theme": "地产链", "stocks": []}, {"theme": "化工", "stocks": []}],
            "an": [{"theme": "房地产", "stocks": []}, {"theme": "农药", "stocks": []}],
            "ar": [{"theme": "锂电池", "stocks": []}],
        }
        reverse = {
            # Two labels from the same real-estate family are only one concept.
            "000101": {"name": "地产标签拆分", "tags": ["地产链", "房地产"]},
            # Real estate + battery are distinct families and qualify.
            "000102": {"name": "跨概念交集", "tags": ["房地产", "钠电池"]},
            # Chemical and pesticide labels describe one theme family too.
            "000106": {"name": "化工标签拆分", "tags": ["化工", "农药"]},
            "000103": {"name": "ST交集", "tags": ["地产链", "锂电池"]},
            "000104": {"name": "*ST交集", "tags": ["地产链", "锂电池"]},
            "000105": {"name": "S*ST交集", "tags": ["地产链", "锂电池"]},
        }

        result = build_attention_mk(board, reverse)

        self.assertEqual([row["name"] for row in result["matches"]], ["跨概念交集"])
        self.assertEqual(result["matches"][0]["match_count"], 2)
        self.assertEqual(result["matches"][0]["matched_keywords"], ["地产链", "锂电池"])
        self.assertEqual(result["matches"][0]["matched_concepts"], ["房地产", "电池"])
        self.assertEqual(result["keyword_concepts"]["房地产"], "房地产")
        self.assertEqual(result["keyword_concepts"]["锂电池"], "电池")


if __name__ == "__main__":
    unittest.main()
