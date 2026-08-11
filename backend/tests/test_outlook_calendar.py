from application.outlook_calendar import subtract_busy_intervals


def test_outlook_busy_periods_are_removed_from_app_availability():
    available = [
        {"start_time": "09:00", "end_time": "10:00"},
        {"start_time": "10:00", "end_time": "11:00"},
        {"start_time": "11:00", "end_time": "12:00"},
    ]
    busy = [{"start_time": "09:30", "end_time": "10:30", "source": "outlook"}]

    assert subtract_busy_intervals(available, busy) == [
        {"start_time": "11:00", "end_time": "12:00"}
    ]


def test_free_and_cancelled_outlook_events_do_not_block_slots():
    available = [{"start_time": "09:00", "end_time": "10:00"}]
    busy = [
        {"start_time": "09:00", "end_time": "10:00", "show_as": "free"},
        {"start_time": "09:00", "end_time": "10:00", "is_cancelled": True},
    ]
    assert subtract_busy_intervals(available, busy) == available

