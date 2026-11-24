import unittest
from datetime import datetime, timedelta

from svitlo_alert.config import KYIV
from svitlo_alert.schedule import Change, Snapshot, Zone, merge_slots, next_change
from svitlo_alert.texts import change_message

DAY_FROM = "2026-11-24T22:00:00.000000Z"  # 25.11 00:00 за Києвом


def make_raw(series, schedules_from=(DAY_FROM,)):
    time_series = []
    for i in range(48):
        start = timedelta(minutes=30 * i)
        end = start + timedelta(minutes=30)
        fmt = lambda td: f"{int(td.total_seconds() // 3600) % 24:02d}:{int(td.total_seconds() // 60 % 60):02d}:00"
        time_series.append({"id": i + 1, "start": fmt(start), "end": fmt(end)})
    return {
        "fetched_at": "2026-11-25T00:00:00+02:00",
        "queues": [{"id": 21, "name": "4.1", "deleted": 0}, {"id": 22, "name": "4.2", "deleted": 0}],
        "time_series": time_series,
        "schedules": [
            {"from": f, "series": series if n == 0 else []} for n, f in enumerate(schedules_from)
        ],
    }


def cell(slot, type_, queue=21):
    return {"outage_queue_id": queue, "time_series_id": slot, "type": type_}


def at(h, m=0):
    return datetime(2026, 11, 25, h, m, tzinfo=KYIV)


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        # 4.1: 08:00-09:00 жовта, 09:00-11:00 червона, 11:00-11:30 жовта
        series = [cell(17, "PROBABLY_OFF"), cell(18, "PROBABLY_OFF")]
        series += [cell(s, "OFF") for s in (19, 20, 21)] + [cell(22, "SURE_OFF")]
        series += [cell(23, "PROBABLY_OFF"), cell(19, "SURE_OFF", queue=22)]
        self.snap = Snapshot.from_raw(make_raw(series))

    def test_green_to_yellow(self):
        change = next_change(self.snap.timeline(21, at(7, 10)), at(7, 10))
        self.assertEqual(change, Change(at(8), Zone.GREEN, Zone.YELLOW))
        self.assertIn("жовта", change_message(change, "4.1"))
        self.assertIn("08:00", change_message(change, "4.1"))

    def test_yellow_to_red(self):
        change = next_change(self.snap.timeline(21, at(8, 40)), at(8, 40))
        self.assertEqual(change, Change(at(9), Zone.YELLOW, Zone.RED))
        self.assertIn("червона", change_message(change, "4.1"))

    def test_red_to_yellow_and_yellow_to_green(self):
        change = next_change(self.snap.timeline(21, at(10)), at(10))
        self.assertEqual(change, Change(at(11), Zone.RED, Zone.YELLOW))
        self.assertIn("можливе світло", change_message(change, "4.1"))
        change = next_change(self.snap.timeline(21, at(11, 10)), at(11, 10))
        self.assertEqual(change, Change(at(11, 30), Zone.YELLOW, Zone.GREEN))
        self.assertIn("можливе світло", change_message(change, "4.1"))

    def test_groups_are_independent(self):
        change = next_change(self.snap.timeline(22, at(7)), at(7))
        self.assertEqual(change, Change(at(9), Zone.GREEN, Zone.RED))

    def test_no_change_till_end_of_known_schedule(self):
        self.assertIsNone(next_change(self.snap.timeline(21, at(12)), at(12)))

    def test_merge(self):
        parts = merge_slots([s for s in self.snap.timeline(21, at(0)) if s.start.date() == at(0).date()])
        self.assertEqual([(p.start.hour, p.zone) for p in parts],
                         [(0, Zone.GREEN), (8, Zone.YELLOW), (9, Zone.RED), (11, Zone.YELLOW), (11, Zone.GREEN)])
        self.assertEqual(parts[-1].end, at(0) + timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
