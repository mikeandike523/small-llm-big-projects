from click.testing import CliRunner

from src.cli_obj import cli
from src.cli_routes import process_doctor as route
from src.utils.process_doctor import MatchedProcess


def _match(pid: int) -> MatchedProcess:
    return MatchedProcess(
        pid=pid,
        ppid=None,
        role="proxy",
        create_time=0,
        cmdline="node proxy-server/index.js",
        ports=[],
    )


def test_force_kill_all_is_non_interactive(monkeypatch):
    killed = []
    monkeypatch.setattr(route, "find_slbp_processes", lambda: [_match(12), _match(34)])
    monkeypatch.setattr(
        route, "kill_process", lambda pid: (killed.append(pid) is None, f"Killed {pid}")
    )

    result = CliRunner().invoke(cli, ["process-doctor", "--force-kill-all"])

    assert result.exit_code == 0
    assert killed == [12, 34]
    assert "Force-killing 2" in result.output


def test_force_kill_all_fails_when_a_process_cannot_be_killed(monkeypatch):
    monkeypatch.setattr(route, "find_slbp_processes", lambda: [_match(12)])
    monkeypatch.setattr(route, "kill_process", lambda _pid: (False, "Access denied"))

    result = CliRunner().invoke(cli, ["process-doctor", "--force-kill-all"])

    assert result.exit_code != 0
    assert "Failed to kill 1 of 1" in result.output
