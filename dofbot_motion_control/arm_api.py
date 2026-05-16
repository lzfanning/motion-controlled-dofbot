"""HTTP endpoints for direct arm control.

This is a bonus interface to control the arm over HTTP.
The web UI in index.html does not use these routes.
"""
import time

from flask import Blueprint, jsonify, request


arm_api = Blueprint("arm_api", __name__)

_SERVO_LIMITS = {
    1: (0, 180),
    2: (0, 180),
    3: (0, 180),
    4: (0, 180),
    5: (0, 270),
    6: (0, 180),
}

_HOME = [90, 130, 0, 0, 90, 60]
_GRIP_OPEN = 60
_GRIP_CLOSE = 135

_DEFAULT_MOVE_MS = 1000
_DEFAULT_JOINT_MS = 500
_DEFAULT_GRIP_MS = 400
_SETTLE_PAD_S = 0.2
_READ_JOINT_PAUSE_S = 0.02

_arm = None


def init_arm_api(arm):
    """Provides the shared Arm_Device instance to this blueprint."""
    global _arm
    _arm = arm


def clamp_angle(servo_id, angle):
    lo, hi = _SERVO_LIMITS[servo_id]
    return max(lo, min(hi, angle))


@arm_api.route("/home", methods=["POST"])
def home():
    ms = request.json.get("ms", _DEFAULT_MOVE_MS) if request.json else _DEFAULT_MOVE_MS
    _arm.Arm_serial_servo_write6_array(_HOME, ms)
    time.sleep(ms / 1000.0 + _SETTLE_PAD_S)
    return jsonify(status="ok", joints=_HOME)


@arm_api.route("/move_joints", methods=["POST"])
def move_joints():
    data = request.json
    joints = data["joints"]
    ms = data.get("ms", _DEFAULT_MOVE_MS)

    if len(joints) != 6:
        return jsonify(status="error", message="joints must have 6 elements"), 400

    clamped = [clamp_angle(i + 1, a) for i, a in enumerate(joints)]
    _arm.Arm_serial_servo_write6_array(clamped, ms)
    time.sleep(ms / 1000.0 + _SETTLE_PAD_S)
    return jsonify(status="ok", joints=clamped)


@arm_api.route("/move_joint", methods=["POST"])
def move_joint():
    data = request.json
    servo_id = data["servo_id"]
    angle = data["angle"]
    ms = data.get("ms", _DEFAULT_JOINT_MS)

    if servo_id not in _SERVO_LIMITS:
        return jsonify(status="error", message="servo_id must be 1-6"), 400

    clamped = clamp_angle(servo_id, angle)
    _arm.Arm_serial_servo_write(servo_id, clamped, ms)
    time.sleep(ms / 1000.0 + _SETTLE_PAD_S)
    return jsonify(status="ok", servo_id=servo_id, angle=clamped)


@arm_api.route("/read_joint", methods=["POST"])
def read_joint():
    data = request.json
    servo_id = data["servo_id"]

    if servo_id not in _SERVO_LIMITS:
        return jsonify(status="error", message="servo_id must be 1-6"), 400

    angle = _arm.Arm_serial_servo_read(servo_id)
    return jsonify(status="ok", servo_id=servo_id, angle=angle)


@arm_api.route("/read_joints", methods=["GET"])
def read_joints():
    angles = []
    for i in range(1, 7):
        angles.append(_arm.Arm_serial_servo_read(i))
        time.sleep(_READ_JOINT_PAUSE_S)
    return jsonify(status="ok", joints=angles)


@arm_api.route("/gripper", methods=["POST"])
def gripper():
    data = request.json
    action = data["action"]
    ms = data.get("ms", _DEFAULT_GRIP_MS)

    if action == "open":
        _arm.Arm_serial_servo_write(6, _GRIP_OPEN, ms)
    elif action == "close":
        _arm.Arm_serial_servo_write(6, _GRIP_CLOSE, ms)
    else:
        return jsonify(status="error", message="action must be 'open' or 'close'"), 400

    time.sleep(ms / 1000.0 + _SETTLE_PAD_S)
    return jsonify(status="ok", action=action)


@arm_api.route("/beep", methods=["POST"])
def beep():
    units = request.json.get("units", 1) if request.json else 1
    _arm.Arm_Buzzer_On(units)
    return jsonify(status="ok")


@arm_api.route("/led", methods=["POST"])
def led():
    data = request.json
    _arm.Arm_RGB_set(data["r"], data["g"], data["b"])
    return jsonify(status="ok")


@arm_api.route("/torque", methods=["POST"])
def torque():
    data = request.json
    enabled = data["enabled"]
    _arm.Arm_serial_set_torque(1 if enabled else 0)
    return jsonify(status="ok", enabled=enabled)
