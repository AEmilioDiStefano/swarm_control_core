#!/usr/bin/env python3
"""Regression tests for the unit executor ExecutePlaybook action path.

History: execute_cb() guarded the action path with an undefined name
(HAS_FLEET_ACTION), so the ROS action path raised NameError the moment the
optional action package was installed, while the topic fallback path masked
the failure in local runs. These tests pin the guard to the imported
HAS_PLAYBOOK_ACTION flag and exercise the action path end-to-end with the
action type stubbed, so the action path can never silently regress again.
"""

import inspect
from types import SimpleNamespace

import swarm_control_core.unit_executor_action_server as executor_module


class _FakeActionType:
    """Stand-in for the optional ExecutePlaybook action type."""

    class Feedback:
        """Attribute bag matching ExecutePlaybook.Feedback usage."""

    class Result:
        """Attribute bag matching ExecutePlaybook.Result usage."""


class _FakeGoalHandle:
    """Minimal goal handle covering exactly what execute_cb touches."""

    def __init__(self):
        self.request = SimpleNamespace(
            command_id="hold",
            parameters_json="{}",
            intent_id="intent-1",
            north_m=0.0,
            east_m=0.0,
        )
        self.succeeded = False
        self.aborted = False

    def succeed(self):
        self.succeeded = True

    def abort(self):
        self.aborted = True


class _FakeExecutor:
    """Minimal UnitExecutor stand-in providing only what execute_cb uses."""

    def __init__(self, success=True, reason="ok"):
        self._active_goals = {}
        self._core_calls = []
        self._result_calls = []
        self._success = success
        self._reason = reason

    def _publish_feedback_safe(self, goal_handle, feedback, percent, text):
        pass

    def _execute_command_core(self, **kwargs):
        self._core_calls.append(kwargs)
        return self._success, self._reason, {}

    def _set_result_safe(self, result, success, text):
        self._result_calls.append((result, success, text))


def test_module_does_not_reference_undefined_action_flag():
    """Tripwire for the historical HAS_FLEET_ACTION NameError regression."""
    source = inspect.getsource(executor_module)
    assert "HAS_FLEET_ACTION" not in source, (
        "unit_executor_action_server references HAS_FLEET_ACTION, which is "
        "never defined; the action guard must use HAS_PLAYBOOK_ACTION."
    )


def test_execute_cb_returns_none_without_action_interface(monkeypatch):
    """The guard exits before touching self when the action package is absent."""
    monkeypatch.setattr(executor_module, "HAS_PLAYBOOK_ACTION", False)
    bare_self = object()  # any attribute access would raise AttributeError
    result = executor_module.UnitExecutor.execute_cb(bare_self, _FakeGoalHandle())
    assert result is None


def test_execute_cb_action_path_succeeds_goal(monkeypatch):
    """With the action interface present (stubbed) a goal executes and succeeds."""
    monkeypatch.setattr(executor_module, "HAS_PLAYBOOK_ACTION", True)
    monkeypatch.setattr(executor_module, "ExecutePlaybook", _FakeActionType)

    fake_self = _FakeExecutor(success=True, reason="done")
    handle = _FakeGoalHandle()
    result = executor_module.UnitExecutor.execute_cb(fake_self, handle)

    assert isinstance(result, _FakeActionType.Result)
    assert handle.succeeded and not handle.aborted
    assert len(fake_self._core_calls) == 1
    core_call = fake_self._core_calls[0]
    assert core_call["command_id"] == "hold"
    assert core_call["intent_id"] == "intent-1"
    assert core_call["stop_event"] is not None
    assert fake_self._result_calls == [(result, True, "done")]
    # The stop-event registry must be cleaned up after the goal completes.
    assert fake_self._active_goals == {}


def test_execute_cb_action_path_aborts_failed_goal(monkeypatch):
    """A failed command aborts the goal and still cleans up goal state."""
    monkeypatch.setattr(executor_module, "HAS_PLAYBOOK_ACTION", True)
    monkeypatch.setattr(executor_module, "ExecutePlaybook", _FakeActionType)

    fake_self = _FakeExecutor(success=False, reason="validation rejected")
    handle = _FakeGoalHandle()
    result = executor_module.UnitExecutor.execute_cb(fake_self, handle)

    assert isinstance(result, _FakeActionType.Result)
    assert handle.aborted and not handle.succeeded
    assert fake_self._result_calls == [(result, False, "validation rejected")]
    assert fake_self._active_goals == {}
