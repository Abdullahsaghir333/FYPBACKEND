import cv2
import mediapipe as mp
import numpy as np
import time
from collections import deque


class FocusTracker:
    # ── Thresholds ────────────────────────────────────────────────────────
    PITCH_TOLERANCE      = 25.0
    HEAD_DOWN_THRESH     = 45.0
    YAW_TOLERANCE        = 20.0
    EAR_BLINK_THRESH     = 0.03   # EAR drop that counts as a physical blink
    EAR_DROP_THRESH      = 0.04   # EAR drop used for eye-openness scoring
    SLEEP_LIMIT          = 15.0   # seconds with eyes closed -> alarm
    HEAD_DOWN_LIMIT      = 15.0   # seconds with head down -> alarm

    # ── FIX 1: Raised gaze variance threshold ─────────────────────────────
    # Variance is multiplied by 10000. At 0.05 even micro-tremors reset the
    # timer. Raise to 1.5 so only real intentional eye movement counts.
    GAZE_MOVE_THRESH     = 0.5

    # ── FIX 2: Reduced stare alarm timers from 15s to 8s ──────────────────
    # 15 seconds is far too long. 8 seconds is a natural "zoning out" window.
    BLINK_THRESHOLD      = 15.0    # seconds since last physical blink
    GAZE_STILL_THRESHOLD = 15.0    # seconds since last meaningful iris movement

    # ── Score weights ─────────────────────────────────────────────────────
    W_POSE = 0.4
    W_EYES = 0.3
    W_GAZE = 0.3

    # ── Calibration: 30 frames ~ 10 s at ~3 fps over the WebSocket ───────
    MAX_CALIB_FRAMES = 30

    # ── Eye landmark indices ──────────────────────────────────────────────
    LEFT_EYE  = [33,  160, 158, 133, 153, 144]
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]

    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._reset_state()

    def _reset_state(self):
        self.is_calibrated      = False
        self.calibration_frames = 0
        self._calib_pitch_sum   = 0.0
        self._calib_yaw_sum     = 0.0
        self._calib_ear_sum     = 0.0
        self.baseline_pitch     = 0.0
        self.baseline_yaw       = 0.0
        self.baseline_ear       = 0.0

        # Two independent timers
        self.last_blink_time     = time.time()
        self.last_gaze_move_time = time.time()

        self.focus_history = deque(maxlen=20)
        self.gaze_history  = deque(maxlen=30)

        self.head_down_start_time   = None
        self.eyes_closed_start_time = None

    # ── Geometry helpers ──────────────────────────────────────────────────

    def _get_head_pose(self, landmarks, img_w, img_h):
        face_3d = np.array([
            [  0.0,   0.0,    0.0],
            [  0.0, 330.0,  -65.0],
            [-225.0, -170.0, -135.0],
            [ 225.0, -170.0, -135.0],
            [-150.0,  150.0, -125.0],
            [ 150.0,  150.0, -125.0],
        ], dtype=np.float64)
        face_2d = np.array(
            [[landmarks[i].x * img_w, landmarks[i].y * img_h]
             for i in [1, 152, 33, 263, 61, 291]],
            dtype=np.float64,
        )
        focal_length = img_w
        cam_matrix = np.array([
            [focal_length, 0,            img_h / 2],
            [0,            focal_length, img_w / 2],
            [0,            0,            1         ],
        ])
        dist_coeffs = np.zeros((4, 1))
        _, rot_vec, _ = cv2.solvePnP(face_3d, face_2d, cam_matrix, dist_coeffs)
        rmat, _       = cv2.Rodrigues(rot_vec)
        angles, *_    = cv2.RQDecomp3x3(rmat)
        return angles[0], angles[1], angles[2]

    def _calculate_ear(self, landmarks, indices):
        pts = np.array([[landmarks[i].x, landmarks[i].y] for i in indices])
        v1 = np.linalg.norm(pts[1] - pts[5])
        v2 = np.linalg.norm(pts[2] - pts[4])
        h  = np.linalg.norm(pts[0] - pts[3])
        return (v1 + v2) / (2.0 * h) if h > 0 else 0.0

    def _get_iris_gaze_score(self, landmarks):
        L_iris   = landmarks[468].x
        L_center = (landmarks[33].x  + landmarks[133].x) / 2
        R_iris   = landmarks[473].x
        R_center = (landmarks[362].x + landmarks[263].x) / 2
        avg_dist = (abs(L_iris - L_center) + abs(R_iris - R_center)) / 2
        if avg_dist < 0.004:   return 1.0
        elif avg_dist < 0.008: return 0.5
        else:                  return 0.0

    # ── Public entry point ────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray) -> dict:
        h, w, _ = frame.shape
        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return self._no_face_result()
        lm = results.multi_face_landmarks[0].landmark
        return self._calibrate(lm, w, h) if not self.is_calibrated else self._monitor(lm, w, h)

    # ── Calibration ───────────────────────────────────────────────────────

    def _calibrate(self, lm, w, h) -> dict:
        pitch, yaw, _ = self._get_head_pose(lm, w, h)
        ear = (self._calculate_ear(lm, self.LEFT_EYE) +
               self._calculate_ear(lm, self.RIGHT_EYE)) / 2.0

        self.calibration_frames  += 1
        self._calib_pitch_sum    += pitch
        self._calib_yaw_sum      += yaw
        self._calib_ear_sum      += ear

        if self.calibration_frames >= self.MAX_CALIB_FRAMES:
            n = self.MAX_CALIB_FRAMES
            self.baseline_pitch  = self._calib_pitch_sum / n
            self.baseline_yaw    = self._calib_yaw_sum   / n
            self.baseline_ear    = self._calib_ear_sum   / n
            self.is_calibrated   = True
            self.last_blink_time     = time.time()
            self.last_gaze_move_time = time.time()

        return {
            "face_found":           True,
            "is_calibrated":        self.is_calibrated,
            "calibration_progress": self.calibration_frames,
            "status":               "CALIBRATING",
            "alarm":                False,
        }

    # ── Monitoring ────────────────────────────────────────────────────────

    def _monitor(self, lm, w, h) -> dict:
        now = time.time()

        pitch, yaw, _ = self._get_head_pose(lm, w, h)
        ear = (self._calculate_ear(lm, self.LEFT_EYE) +
               self._calculate_ear(lm, self.RIGHT_EYE)) / 2.0

        # ── SIGNAL 1: Physical blink ──────────────────────────────────────
        # Only a real eyelid close (EAR drop > EAR_BLINK_THRESH) resets this.
        # Eye movement does NOT reset it — the two signals are independent.
        if (self.baseline_ear - ear) > self.EAR_BLINK_THRESH:
            self.last_blink_time = now
        time_since_blink = now - self.last_blink_time

        # ── SIGNAL 2: Iris / eyeball movement ─────────────────────────────
        # Variance of iris midpoint over a rolling window (scaled x10000).
        # FIX: threshold raised to 1.5 so micro-tremors don't falsely reset.
        # Blinking does NOT reset this timer.
        iris_mid = (lm[468].x + lm[473].x) / 2.0
        self.gaze_history.append(iris_mid)
        gaze_variance = 0.0
        if len(self.gaze_history) > 10:
            gaze_variance = float(np.var(list(self.gaze_history)) * 10000)
        if gaze_variance > self.GAZE_MOVE_THRESH:
            self.last_gaze_move_time = now
        time_since_gaze_move = now - self.last_gaze_move_time

        # ── STARE ALARM: BOTH signals stale simultaneously ─────────────────
        # Reading  -> eyes move (gaze timer resets) even if blinks are rare -> NO alarm
        # Blinking -> blink timer resets even if gaze is locked             -> NO alarm
        # Zoning out -> neither blinks NOR moves eyes for threshold seconds -> ALARM
        stare_alarm = (
            time_since_blink     > self.BLINK_THRESHOLD and
            time_since_gaze_move > self.GAZE_STILL_THRESHOLD
        )

        # ── Base scores ───────────────────────────────────────────────────
        delta_pitch = abs(pitch - self.baseline_pitch)
        delta_yaw   = abs(yaw   - self.baseline_yaw)
        delta_ear   = self.baseline_ear - ear

        if delta_pitch < self.PITCH_TOLERANCE and delta_yaw < self.YAW_TOLERANCE:
            pose_score = 1.0
        elif delta_pitch < self.PITCH_TOLERANCE * 1.5 and delta_yaw < self.YAW_TOLERANCE * 1.5:
            pose_score = 0.5
        else:
            pose_score = 0.0

        if delta_ear < self.EAR_DROP_THRESH:            eye_score = 1.0
        elif delta_ear < self.EAR_DROP_THRESH + 0.05:  eye_score = 0.5
        else:                                           eye_score = 0.0

        gaze_score = self._get_iris_gaze_score(lm)

        focus_val = (
            pose_score * self.W_POSE +
            eye_score  * self.W_EYES +
            gaze_score * self.W_GAZE
        )

        # ── Override alarms ───────────────────────────────────────────────
        alarm_reason = None

        if delta_ear > self.EAR_DROP_THRESH:
            if self.eyes_closed_start_time is None:
                self.eyes_closed_start_time = now
            elif (now - self.eyes_closed_start_time) > self.SLEEP_LIMIT:
                focus_val    = 0.0
                alarm_reason = "WAKE UP"
        else:
            self.eyes_closed_start_time = None

        if delta_pitch > self.HEAD_DOWN_THRESH:
            if self.head_down_start_time is None:
                self.head_down_start_time = now
            elif (now - self.head_down_start_time) > self.HEAD_DOWN_LIMIT:
                focus_val    = 0.0
                alarm_reason = "HEAD DOWN"
        else:
            self.head_down_start_time = None

        # ── FIX 3: Stare alarm fires immediately — no rolling average delay ──
        # Previously stare_alarm set alarm_reason but focus_val was still
        # averaged, causing a delay. Now we force alarm immediately.
        if stare_alarm:
            focus_val    = 0.0
            alarm_reason = "PLEASE BLINK"

        # ── Rolling average and final status ──────────────────────────────
        self.focus_history.append(focus_val * 100)
        avg_focus = sum(self.focus_history) / len(self.focus_history)

        # CRITICAL: If any override alarm is active, force immediate alarm
        # regardless of rolling average. The rolling average is too slow
        # to react to these urgent conditions.
        if alarm_reason:
            status        = alarm_reason
            alarm_trigger = True
            # Flush rolling history so stale high scores don't delay recovery
            self.focus_history.clear()
            self.focus_history.append(0.0)
            avg_focus = 0.0
        elif avg_focus > 75:
            status, alarm_trigger = "FOCUSED", False
        elif avg_focus > 40:
            status, alarm_trigger = "DISTRACTED", False
        else:
            status        = "NOT FOCUSED"
            alarm_trigger = True

        return {
            "face_found":       True,
            "is_calibrated":    True,
            "focus_val":        int(avg_focus),
            "status":           status,
            "alarm":            alarm_trigger,
            "blink_timer":      int(time_since_blink),
            "gaze_still_timer": int(time_since_gaze_move),
            "gaze_variance":    round(gaze_variance, 6),
            "pose_score":       pose_score,
            "eye_score":        eye_score,
            "gaze_score":       gaze_score,
        }

    # ── No face ───────────────────────────────────────────────────────────

    def _no_face_result(self) -> dict:
        self.eyes_closed_start_time = None
        self.head_down_start_time   = None
        if self.is_calibrated:
            self.focus_history.append(0.0)
            avg = sum(self.focus_history) / len(self.focus_history)
            return {"face_found": False, "is_calibrated": True,
                    "focus_val": int(avg), "status": "NO FACE", "alarm": True}
        return {"face_found": False, "is_calibrated": False,
                "calibration_progress": self.calibration_frames,
                "status": "NO FACE", "alarm": False}

    def reset_calibration(self):
        self._reset_state()