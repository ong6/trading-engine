"""Tests for read-only scheduler host probes."""

from subprocess import CompletedProcess

from server import scheduler_host


def test_cron_probe_units_are_unique_and_expected():
    assert scheduler_host.CRON_SERVICE_UNITS == ("cron", "crond")
    assert len(scheduler_host.CRON_SERVICE_UNITS) == len(
        set(scheduler_host.CRON_SERVICE_UNITS)
    )


def test_read_user_crontab_distinguishes_absent_from_broken(monkeypatch):
    results = iter(
        (
            CompletedProcess(("crontab", "-l"), 1, stdout="", stderr="no crontab for test\n"),
            CompletedProcess(("crontab", "-l"), 2, stdout="", stderr="permission denied\n"),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.read_user_crontab() == ("", None)
    assert scheduler_host.read_user_crontab() == (None, "crontab-unreadable")


def test_read_user_crontab_handles_command_exception(monkeypatch):
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: None)

    assert scheduler_host.read_user_crontab() == (None, "crontab-unreadable")


def test_read_user_crontab_rejects_noisy_success_or_ambiguous_absence(monkeypatch):
    results = iter(
        (
            CompletedProcess(("crontab", "-l"), 0, stdout="entry\n", stderr="warning\n"),
            CompletedProcess(
                ("crontab", "-l"), 1, stdout="partial\n", stderr="no crontab for test\n"
            ),
            CompletedProcess(
                ("crontab", "-l"), 1, stdout="", stderr="warning: no crontab for test\n"
            ),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.read_user_crontab() == (None, "crontab-unreadable")
    assert scheduler_host.read_user_crontab() == (None, "crontab-unreadable")
    assert scheduler_host.read_user_crontab() == (None, "crontab-unreadable")


def test_cron_service_falls_back_to_active_crond(monkeypatch):
    results = iter(
        (
            CompletedProcess(
                ("systemctl",),
                0,
                stdout="LoadState=not-found\nActiveState=inactive\n",
                stderr="",
            ),
            CompletedProcess(
                ("systemctl",), 0, stdout="LoadState=loaded\nActiveState=active\n", stderr=""
            ),
        )
    )
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return next(results)

    monkeypatch.setattr(scheduler_host, "run_bounded", run)

    assert scheduler_host.cron_service() == ("active", "crond")
    assert [call[0][0][1:3] for call in calls] == [["show", "cron"], ["show", "crond"]]


def test_cron_service_skips_missing_alias_before_installed_failure(monkeypatch):
    results = iter(
        (
            CompletedProcess(
                ("systemctl",),
                0,
                stdout="LoadState=not-found\nActiveState=inactive\n",
                stderr="",
            ),
            CompletedProcess(
                ("systemctl",), 0, stdout="LoadState=loaded\nActiveState=failed\n", stderr=""
            ),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.cron_service() == ("failed", "crond")


def test_cron_service_reports_unknown_when_both_aliases_are_missing(monkeypatch):
    monkeypatch.setattr(
        scheduler_host,
        "run_bounded",
        lambda *args, **kwargs: CompletedProcess(
            ("systemctl",),
            0,
            stdout="LoadState=not-found\nActiveState=inactive\n",
            stderr="",
        ),
    )

    assert scheduler_host.cron_service() == ("unknown", None)


def test_cron_service_rejects_contradictory_missing_active_unit(monkeypatch):
    monkeypatch.setattr(
        scheduler_host,
        "run_bounded",
        lambda *args, **kwargs: CompletedProcess(
            ("systemctl",),
            0,
            stdout="LoadState=not-found\nActiveState=active\n",
            stderr="",
        ),
    )

    assert scheduler_host.cron_service() == ("unknown", None)


def test_cron_service_preserves_first_observed_inactive_state(monkeypatch):
    results = iter(
        (
            CompletedProcess(
                ("systemctl",), 0, stdout="LoadState=loaded\nActiveState=failed\n", stderr=""
            ),
            CompletedProcess(
                ("systemctl",), 0, stdout="LoadState=loaded\nActiveState=unknown\n", stderr=""
            ),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.cron_service() == ("failed", "cron")


def test_cron_service_preserves_first_observation_when_alternate_probe_is_unavailable(
    monkeypatch,
):
    results = iter(
        (
            CompletedProcess(
                ("systemctl",),
                0,
                stdout="LoadState=loaded\nActiveState=inactive\n",
                stderr="",
            ),
            None,
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.cron_service() == ("inactive", "cron")


def test_cron_service_handles_command_exception(monkeypatch):
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: None)

    assert scheduler_host.cron_service() == ("unknown", None)


def test_cron_service_normalizes_undocumented_output(monkeypatch):
    monkeypatch.setattr(
        scheduler_host,
        "run_bounded",
        lambda *args, **kwargs: CompletedProcess(
            ("systemctl",),
            0,
            stdout="LoadState=invented\nActiveState=inactive\n",
            stderr="",
        ),
    )

    assert scheduler_host.cron_service() == ("unknown", None)


def test_cron_service_rejects_noisy_or_exit_incoherent_state(monkeypatch):
    results = iter(
        (
            CompletedProcess(
                ("systemctl",),
                0,
                stdout="LoadState=loaded\nActiveState=active\n",
                stderr="warning\n",
            ),
            CompletedProcess(
                ("systemctl",), 3, stdout="LoadState=loaded\nActiveState=active\n", stderr=""
            ),
            CompletedProcess(
                ("systemctl",), 0, stdout="LoadState=loaded\nActiveState=unknown\n", stderr=""
            ),
            CompletedProcess(
                ("systemctl",),
                0,
                stdout="LoadState= loaded \nActiveState=active\n",
                stderr="",
            ),
            CompletedProcess(("systemctl",), 0, stdout="LoadState=loaded\n", stderr=""),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.cron_service() == ("unknown", None)
    assert scheduler_host.cron_service() == ("unknown", None)
    assert scheduler_host.cron_service() == ("unknown", None)
    assert scheduler_host.cron_service() == ("unknown", None)
    assert scheduler_host.cron_service() == ("unknown", None)


def test_system_timezone_reads_value_and_fails_closed(monkeypatch):
    results = iter(
        (
            CompletedProcess(("timedatectl",), 0, stdout="Etc/UTC\n", stderr=""),
            CompletedProcess(("timedatectl",), 1, stdout="", stderr="unavailable\n"),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.system_timezone() == "Etc/UTC"
    assert scheduler_host.system_timezone() == "unknown"


def test_system_timezone_rejects_multiline_nonprintable_and_oversized_output(monkeypatch):
    results = iter(
        CompletedProcess(("timedatectl",), 0, stdout=value, stderr="")
        for value in (
            "UTC\nEtc/UTC\n",
            "UTC\x00",
            "x" * (scheduler_host.PUBLIC_TIMEZONE_MAX_CHARS + 1),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.system_timezone() == "unknown"
    assert scheduler_host.system_timezone() == "unknown"
    assert scheduler_host.system_timezone() == "unknown"


def test_system_timezone_accepts_exact_public_character_budget(monkeypatch):
    timezone_name = "x" * scheduler_host.PUBLIC_TIMEZONE_MAX_CHARS
    monkeypatch.setattr(
        scheduler_host,
        "run_bounded",
        lambda *args, **kwargs: CompletedProcess(
            ("timedatectl",), 0, stdout=f"{timezone_name}\n", stderr=""
        ),
    )

    assert scheduler_host.system_timezone() == timezone_name


def test_system_timezone_rejects_diagnostic_or_noncanonical_framing(monkeypatch):
    results = iter(
        (
            CompletedProcess(("timedatectl",), 0, stdout="Etc/UTC\n", stderr="warning\n"),
            CompletedProcess(("timedatectl",), 0, stdout=" Etc/UTC \n", stderr=""),
            CompletedProcess(("timedatectl",), 0, stdout="Etc/UTC", stderr=""),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.system_timezone() == "unknown"
    assert scheduler_host.system_timezone() == "unknown"
    assert scheduler_host.system_timezone() == "unknown"


def test_service_enabled_reads_value_and_fails_closed(monkeypatch):
    results = iter(
        (
            CompletedProcess(("systemctl",), 0, stdout="enabled\n", stderr=""),
            CompletedProcess(("systemctl",), 1, stdout="", stderr="unavailable\n"),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.service_enabled("cron") == "enabled"
    assert scheduler_host.service_enabled("cron") == "unknown"
    assert scheduler_host.service_enabled(None) == "unknown"


def test_service_enabled_normalizes_undocumented_output(monkeypatch):
    monkeypatch.setattr(
        scheduler_host,
        "run_bounded",
        lambda *args, **kwargs: CompletedProcess(
            ("systemctl",), 1, stdout="invented\n", stderr=""
        ),
    )

    assert scheduler_host.service_enabled("cron") == "unknown"


def test_service_enabled_rejects_noisy_or_exit_incoherent_state(monkeypatch):
    results = iter(
        (
            CompletedProcess(("systemctl",), 0, stdout="enabled\n", stderr="warning\n"),
            CompletedProcess(("systemctl",), 1, stdout="enabled\n", stderr=""),
            CompletedProcess(("systemctl",), 0, stdout="disabled\n", stderr=""),
            CompletedProcess(("systemctl",), 0, stdout=" enabled \n", stderr=""),
        )
    )
    monkeypatch.setattr(scheduler_host, "run_bounded", lambda *args, **kwargs: next(results))

    assert scheduler_host.service_enabled("cron") == "unknown"
    assert scheduler_host.service_enabled("cron") == "unknown"
    assert scheduler_host.service_enabled("cron") == "unknown"
    assert scheduler_host.service_enabled("cron") == "unknown"
