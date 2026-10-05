"""Build dated AL/AN/AR boards from a bounded, chronological limit-up window."""

from collections import defaultdict


def _valid_time(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 999999
    return number if 90000 <= number <= 153000 else 999999


def _stock_key(stock):
    level = int(stock.get("level") or 0)
    if stock.get("status") == "big_gain":
        try:
            gain_rank = -float(stock.get("change_pct") or 0)
        except (TypeError, ValueError):
            gain_rank = 0
        return (1, 1, 999999, gain_rank, 0, stock["name"], stock["code"])
    if level >= 2:
        return (0, -level, _valid_time(stock.get("first_time")), 0, -level, stock["name"], stock["code"])
    if level == 1:
        return (1, 0, _valid_time(stock.get("first_time")), 0, -1, stock["name"], stock["code"])
    return (2, 0, 999999, int(stock.get("break_days") or 999),
            -int(stock.get("peak_level") or 0), stock["name"], stock["code"])


def _topic_key(topic):
    lead = topic["stocks"][0]
    return (_stock_key(lead)[:5], -topic["current_2plus_count"],
            -topic["current_first_count"], topic["theme"])


def _attention_mk_concept_key(keyword):
    """Map labels to broad families so related subtopics count only once in MK."""
    text = "".join(char for char in str(keyword or "").strip().casefold() if char.isalnum())
    if not text:
        return ""
    if "地产" in text or "房地产" in text:
        return "房地产"
    if "电池" in text:
        return "电池"
    if any(token in text for token in ("化工", "染料", "农药", "有机硅", "橡胶")):
        return "化工材料"
    if any(token in text for token in ("医疗", "医药", "创新药", "疫苗", "药", "cro", "细胞治疗", "基因疗法", "保健品", "养老概念")):
        return "医疗健康"
    if "ai" in text or "人工智能" in text:
        return "人工智能"
    if any(token in text for token in ("汽车", "智能驾驶")):
        return "汽车"
    if any(token in text for token in ("芯片", "半导体", "存储", "光刻", "玻璃基板", "电子树脂")):
        return "半导体电子"
    if any(token in text for token in ("电力", "电网", "电源", "风电", "光伏", "热力", "海工装备")):
        return "能源电力"
    if any(token in text for token in ("食品", "饮料", "酿酒", "黄酒", "白酒", "白糖", "乳业", "烟草")):
        return "食品饮料"
    return text


def _attention_mk_is_st(name):
    normalized = str(name or "").strip().casefold()
    return normalized.startswith(("st", "*st", "s*st"))


def build_attention_mk(board, kph_reverse, source_as_of=""):
    """Find non-ST KPH stocks intersecting at least two distinct theme families.

    Industry ``concepts`` are deliberately excluded: MK is a keyword/tag
    intersection, not a broad industry-membership screen. Alias/subtopic labels
    in the real-estate and battery families are collapsed before scoring.
    """
    board = board or {}
    keywords = []
    displayed_codes = set()
    for category in ("al", "an", "ar"):
        for topic in board.get(category, ()) or ():
            name = str(topic.get("theme") or "").strip()
            if name and name not in keywords:
                keywords.append(name)
            for stock in topic.get("stocks", ()) or ():
                code = str(stock.get("code") or "").strip().zfill(6)
                if code.isdigit() and len(code) == 6:
                    displayed_codes.add(code)

    # Keep one representative board keyword per concept family. This prevents
    # aliases (e.g. 地产链/房地产) from appearing as separate evidence.
    keywords_by_concept = {}
    for keyword in keywords:
        concept = _attention_mk_concept_key(keyword)
        if concept:
            keywords_by_concept.setdefault(concept, keyword)

    matches = []
    for raw_code, stock in (kph_reverse or {}).items():
        if not isinstance(stock, dict):
            continue
        code = str(raw_code or "").strip().zfill(6)
        if len(code) != 6 or not code.isdigit() or code in displayed_codes:
            continue
        name = str(stock.get("name") or code).strip()
        if _attention_mk_is_st(name):
            continue
        stock_concepts = {
            _attention_mk_concept_key(tag)
            for tag in (stock.get("tags") or ())
            if _attention_mk_concept_key(tag)
        }
        matched_concepts = [concept for concept in keywords_by_concept if concept in stock_concepts]
        matched = [keywords_by_concept[concept] for concept in matched_concepts]
        if len(matched) < 2:
            continue
        matches.append({
            "code": code,
            "name": name,
            "board": ("创" if code.startswith(("300", "301")) else
                      "科" if code.startswith(("688", "689")) else "主"),
            "match_count": len(matched),
            "matched_keywords": matched,
            "matched_concepts": matched_concepts,
        })
    matches.sort(key=lambda row: (-row["match_count"], row["name"].casefold(), row["code"]))
    return {
        "date": str(board.get("date") or ""),
        "source": "开盘红 KPH 本地题材标签",
        "source_as_of": str(source_as_of or ""),
        "keywords": keywords,
        "keyword_concepts": {
            keyword: _attention_mk_concept_key(keyword)
            for keyword in keywords
        },
        "keyword_count": len(keywords),
        "match_count": len(matches),
        "matches": matches,
    }


def build_attention_days(dates, rows_by_date, pct_by_date=None, cumulative_by_date=None):
    """Return newest-first dated boards, reading only the supplied fifteen-day window.

    Rows are normalized dictionaries with code, name, tags, level and first_time.
    Optional event_type="big_gain" marks a >10% ChiNext/STAR daily move, not a
    limit-up. It is shown in the first-board column with an explicit gain badge;
    once the move is no longer active it is tracked in break+1 / break+N.
    A topic qualifies for AL once any member reaches a continuous second board;
    AR requires first boards by two different stocks on two different dates;
    AN requires a first board today and no topic event in the previous three
    trading sessions.
    """
    ordered_dates = sorted(set(dates))[-15:]
    pct_by_date = pct_by_date or {}
    cumulative_by_date = cumulative_by_date or {}
    if not ordered_dates:
        return []
    date_position = {date: index for index, date in enumerate(ordered_dates)}
    topics = defaultdict(dict)
    snapshots = []
    for day_index, date in enumerate(ordered_dates):
        for raw in rows_by_date.get(date, ()) or ():
            code = str(raw.get("code") or "").zfill(6)
            name = str(raw.get("name") or code).strip()
            if len(code) != 6 or not code.isdigit() or not name:
                continue
            event_type = "big_gain" if raw.get("event_type") == "big_gain" else "limit"
            try:
                level = max(1, int(raw.get("level") or 1)) if event_type == "limit" else 0
            except (TypeError, ValueError):
                level = 1 if event_type == "limit" else 0
            for tag in dict.fromkeys(str(t).strip() for t in (raw.get("tags") or ())):
                if not tag:
                    continue
                stock = topics[tag].setdefault(code, {"code": code, "name": name, "events": {}, "tags": set(), "board": raw.get("board") or "主"})
                stock["name"] = name
                stock["board"] = raw.get("board") or stock.get("board") or "主"
                stock["tags"].update(str(t).strip() for t in (raw.get("tags") or ()) if str(t).strip())
                old = stock["events"].get(date)
                event = {
                    "date": date, "level": level, "event_type": event_type,
                    "first_time": _valid_time(raw.get("first_time")),
                    "change_pct": raw.get("change_pct"),
                    "seal_type": raw.get("seal_type") or (
                        "一字板" if _valid_time(raw.get("first_time")) <= 92530 else
                        "直线板" if _valid_time(raw.get("first_time")) <= 93500 else ""
                    ),
                }
                if old:
                    event["level"] = max(old["level"], event["level"])
                    if old.get("event_type") == "limit":
                        event["event_type"] = "limit"
                    event["first_time"] = min(old["first_time"], event["first_time"])
                    if event["change_pct"] is None:
                        event["change_pct"] = old.get("change_pct")
                stock["events"][date] = event

        board = {"date": date, "window_start": ordered_dates[0], "al": [], "an": [], "ar": []}
        prior_three_dates = set(ordered_dates[max(0, day_index - 3):day_index])
        for tag, stock_map in topics.items():
            all_events = [(code, e) for code, s in stock_map.items() for e in s["events"].values()]
            if not all_events:
                continue
            first_date = min(e["date"] for _, e in all_events)
            limit_events = [(code, e) for code, e in all_events if e.get("event_type") == "limit"]
            has_ladder = any(e["level"] >= 2 for _, e in limit_events)
            first_board_events = [(code, e["date"]) for code, e in limit_events if e["level"] == 1]
            has_rotation = (len({code for code, _ in first_board_events}) >= 2 and
                            len({event_date for _, event_date in first_board_events}) >= 2)
            appeared_recently = any(event.get("date") in prior_three_dates for _, event in all_events)
            has_new_first_board = any(event_date == date for _, event_date in first_board_events) and not appeared_recently
            has_big_gain_history = any(e.get("event_type") == "big_gain" for _, e in all_events)
            if has_ladder:
                category = "al"
            elif has_rotation:
                category = "ar"
            elif has_new_first_board or has_big_gain_history:
                category = "an"
            else:
                continue

            stock_views = []
            for code, stock in stock_map.items():
                events = stock["events"]
                last_date = max(events)
                last_event = events[last_date]
                today = events.get(date)
                break_days = 0 if today else day_index - date_position[last_date]
                peak = max(e["level"] for e in events.values())
                prior_peak = max((e["level"] for event_date, e in events.items() if event_date < date), default=0)
                limit_history = [(event_date, e) for event_date, e in events.items()
                                 if e.get("event_type") == "limit"]
                last_limit = max(limit_history, key=lambda pair: pair[0]) if limit_history else None
                last_level = int(last_limit[1].get("level") or 0) if last_limit else 0
                last_limit_date = last_limit[0] if last_limit else last_date
                last_limit_event = last_limit[1] if last_limit else last_event
                active_big_gain = bool(today and today.get("event_type") == "big_gain")
                # 曾经多板的标的留在最近连板高度层；只有首板断板第1天进入独立的+1列。
                display_level = (int(today["level"]) if today and today.get("event_type") == "limit"
                                 else (1 if active_big_gain else (last_level if last_level >= 2 else 0)))
                break_days = 0 if today else day_index - date_position[last_date]
                last_was_big_gain = last_event.get("event_type") == "big_gain"
                is_low_level_trail = last_level <= 1 or last_was_big_gain
                # +1 专指首板涨停后的首个断板日；大涨回落不计入断板+1，留在断板+N轨迹。
                is_break1 = bool(not today and not last_was_big_gain and last_level == 1 and break_days == 1)
                is_break_n = bool(not today and is_low_level_trail and
                                  (break_days >= 2 or last_was_big_gain and break_days >= 1))
                percent = (pct_by_date.get(date) or {}).get(code)
                if today and percent is None:
                    percent = today.get("change_pct")
                event_history = []
                for event_date in sorted(events):
                    history_event = dict(events[event_date])
                    history_event["change_pct"] = (pct_by_date.get(event_date) or {}).get(code, history_event.get("change_pct"))
                    history_event["cumulative_pct"] = (cumulative_by_date.get(event_date) or {}).get(code)
                    event_history.append(history_event)
                stock_views.append({
                    "code": code, "name": stock["name"],
                    "board": stock.get("board") or "主",
                    "status": ("limit" if today and today.get("event_type") == "limit" else
                               ("big_gain" if active_big_gain else "broken")),
                    "event_type": today.get("event_type") if today else last_event.get("event_type"),
                    "last_event_type": last_event.get("event_type"),
                    "is_big_gain": active_big_gain,
                    "level": today["level"] if today and today.get("event_type") == "limit" else 0,
                    "display_level": display_level,
                    "last_level": last_level,
                    "prior_peak_level": prior_peak,
                    "is_break1": is_break1,
                    "first_time": today["first_time"] if today and today.get("event_type") == "limit" else None,
                    "last_first_time": last_limit_event.get("first_time"),
                    "seal_type": today.get("seal_type") if today and today.get("event_type") == "limit" else last_limit_event.get("seal_type"),
                    "break_days": break_days, "peak_level": peak,
                    "is_break_n": is_break_n,
                    "last_limit_date": last_limit_date,
                    "change_pct": percent,
                    "cumulative_pct": (cumulative_by_date.get(date) or {}).get(code),
                    "tags": sorted(stock["tags"]), "events": event_history,
                })
            stock_views.sort(key=_stock_key)
            # Strength badges are scoped to a topic/day. The existing ordering
            # already encodes board height, first-board seal time, then the
            # nearest broken-day trace, so the visible S-rank stays consistent
            # with the ladder rather than introducing a second sort policy.
            for strength_rank, stock_view in enumerate(stock_views, start=1):
                stock_view["strength_rank"] = strength_rank
            # 只展示所选日仍有涨停/大涨的题材；历史断板轨迹不能单独撑起空题材。
            if not any(s["status"] in ("limit", "big_gain") for s in stock_views):
                continue
            # 保留多板、首板、大涨及单板断板轨迹；断板+N 独立呈现。
            if not any(s["display_level"] >= 1 or s["level"] == 1 or s["is_break1"] or s["is_break_n"] for s in stock_views):
                continue
            current_limit = [s for s in stock_views if s["status"] in ("limit", "big_gain")]
            current_max_level = max((s["level"] for s in stock_views), default=0)
            first_2plus_date = min(
                (event["date"] for _, event in limit_events if event["level"] >= 2),
                default=None,
            )
            if current_max_level > 3:
                guidance = "高位梯队：留意首板补涨与题材扩散，观察梯队承接。"
            elif current_max_level == 3:
                guidance = "最高3板：关注晋级4板与梯队承接，留意首板补涨和20cm弹性。"
            elif current_max_level == 2 and first_2plus_date == date:
                guidance = "首次晋级2板：关注晋级3板后的板块效应、首板伴生龙、N字回流及20cm弹性。"
            elif current_max_level == 2:
                guidance = "最高2板：关注晋级3板后的板块效应、首板伴生龙与20cm弹性，观察题材龙头。"
            elif current_max_level == 1:
                guidance = "当前首板活跃：观察后续晋级与20cm弹性联动。"
            else:
                guidance = "创/科大涨活跃：关注题材联动及后续涨停确认。"
            board[category].append({
                "theme": tag, "category": category, "first_date": first_date,
                "peak_level": max(s["peak_level"] for s in stock_views),
                "current_max_level": current_max_level,
                "guidance": guidance,
                "current_2plus_count": sum(s["level"] >= 2 for s in stock_views),
                "current_first_count": sum(s["level"] == 1 for s in stock_views),
                "current_limit_count": sum(s["status"] == "limit" for s in stock_views),
                "current_big_gain_count": sum(s["is_big_gain"] for s in stock_views),
                "stocks": stock_views,
            })
        for category in ("al", "an", "ar"):
            board[category].sort(key=_topic_key)
        snapshots.append(board)
    return list(reversed(snapshots))
