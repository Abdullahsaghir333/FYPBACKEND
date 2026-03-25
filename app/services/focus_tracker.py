import cv2
import mediapipe as mp
import numpy as np
import time
from collections import deque

class FocusTracker:
    def __init__(self):
        # ── Thresholds ──
        self.PITCH_TOLERANCE = 25.0
        self.HEAD_DOWN_THRESH = 45.0
        self.YAW_TOLERANCE = 20.0
        self.EAR_DROP_THRESH = 0.04
        self.BLINK_THRESHOLD = 15.0
        self.SLEEP_LIMIT = 15.0
        # Sensitivity for eye movement (Lower = easier to detect reading)
        self.GAZE_MOVE_THRESH = 0.005

        # ── Weights ──
        self.W_POSE = 0.4
        self.W_EYES = 0.3
        self.W_GAZE = 0.3

        # ── MediaPipe Face Mesh ──
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # ── Eye landmark indices ──
        self.LEFT_EYE = [33, 160, 158, 133, 153, 144]
        self.RIGHT_EYE = [362, 385, 387, 263, 373, 380]

        # ── Calibration state ──
        self.is_calibrated = False
        self.calibration_frames = 0
        self.MAX_CALIB_FRAMES = 100
        self.baseline_pitch = 0
        self.baseline_yaw = 0
        self.baseline_ear = 0

        # ── Tracking state ──
        self.last_blink_time = time.time()
        self.focus_history = deque(maxlen=20)
        self.gaze_history = deque(maxlen=30)
        self.head_down_start_time = None
        self.eyes_closed_start_time = None

    def get_head_pose(self, landmarks, img_w, img_h):
        face_3d = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 330.0, -65.0],
            [-225.0, -170.0, -135.0],
            [225.0, -170.0, -135.0],
            [-150.0, 150.0, -125.0],
            [150.0, 150.0, -125.0]
        ], dtype=np.float64)

        face_2d = []
        for idx in [1, 152, 33, 263, 61, 291]:
            lm = landmarks[idx]
            face_2d.append([lm.x * img_w, lm.y * img_h])
        face_2d = np.array(face_2d, dtype=np.float64)

        focal_length = 1 * img_w
        cam_matrix = np.array([
            [focal_length, 0, img_h / 2],
            [0, focal_length, img_w / 2],
            [0, 0, 1]
        ])
        dist_coeffs = np.zeros((4, 1))

        success, rot_vec, trans_vec = cv2.solvePnP(face_3d, face_2d, cam_matrix, dist_coeffs)
        rmat, _ = cv2.Rodrigues(rot_vec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)

        return angles[0], angles[1], angles[2]

    def calculate_ear(self, landmarks, indices):
        v1 = np.linalg.norm(np.array([landmarks[indices[1]].x, landmarks[indices[1]].y]) -
                            np.array([landmarks[indices[5]].x, landmarks[indices[5]].y]))
        v2 = np.linalg.norm(np.array([landmarks[indices[2]].x, landmarks[indices[2]].y]) -
                            np.array([landmarks[indices[4]].x, landmarks[indices[4]].y]))
        h = np.linalg.norm(np.array([landmarks[indices[0]].x, landmarks[indices[0]].y]) -
                           np.array([landmarks[indices[3]].x, landmarks[indices[3]].y]))
        return (v1 + v2) / (2.0 * h)

    def get_gaze_score(self, landmarks):
        L_iris = landmarks[468].x
        L_center = (landmarks[33].x + landmarks[133].x) / 2
        R_iris = landmarks[473].x
        R_center = (landmarks[362].x + landmarks[263].x) / 2
        
        avg_dist = (abs(L_iris - L_center) + abs(R_iris - R_center)) / 2
        if avg_dist < 0.004: return 1.0
        elif avg_dist < 0.008: return 0.5
        else: return 0.0

    def process_frame(self, frame):
        h, w, c = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        focus_val = 0.0
        status = "NOT FOCUSED"
        alert_text = None
        alarm_trigger = False

        if results.multi_face_landmarks:
            lm = results.multi_face_landmarks[0].landmark
            pitch, yaw, roll = self.get_head_pose(lm, w, h)
            ear = (self.calculate_ear(lm, self.LEFT_EYE) + self.calculate_ear(lm, self.RIGHT_EYE)) / 2.0
            gaze_score = self.get_gaze_score(lm)

            if not self.is_calibrated:
                self.calibration_frames += 1
                self.baseline_pitch += pitch
                self.baseline_yaw += yaw
                self.baseline_ear += ear

                if self.calibration_frames >= self.MAX_CALIB_FRAMES:
                    self.baseline_pitch /= self.MAX_CALIB_FRAMES
                    self.baseline_yaw /= self.MAX_CALIB_FRAMES
                    self.baseline_ear /= self.MAX_CALIB_FRAMES
                    self.is_calibrated = True
                    self.last_blink_time = time.time()

                return {
                    "face_found": True,
                    "is_calibrated": False,
                    "calibration_progress": self.calibration_frames,
                    "status": "CALIBRATING..."
                }

            # MONITORING PHASE
            # 1. Blink Detection
            if (self.baseline_ear - ear) > 0.03:
                self.last_blink_time = time.time()

            # 2. Eye Movement (Gaze Variance)
            current_gaze_val = (lm[468].x + lm[473].x) / 2.0
            self.gaze_history.append(current_gaze_val)
            gaze_variance = np.var(list(self.gaze_history)) * 10000 if len(self.gaze_history) > 10 else 0.0

            if gaze_variance > self.GAZE_MOVE_THRESH:
                self.last_blink_time = time.time()

            time_since_blink = time.time() - self.last_blink_time

            # 3. Base Scores
            delta_pitch = abs(pitch - self.baseline_pitch)
            delta_yaw = abs(yaw - self.baseline_yaw)
            delta_ear = self.baseline_ear - ear

            # A. Head Pose Score
            if delta_pitch < self.PITCH_TOLERANCE and delta_yaw < self.YAW_TOLERANCE:
                pose_score = 1.0
            elif delta_pitch < self.PITCH_TOLERANCE*1.5 and delta_yaw < self.YAW_TOLERANCE*1.5:
                pose_score = 0.5
            else:
                pose_score = 0.0

            # B. Eye Openness Score
            if delta_ear < self.EAR_DROP_THRESH: 
                eye_score = 1.0 
            elif delta_ear < self.EAR_DROP_THRESH + 0.05: 
                eye_score = 0.5 
            else: 
                eye_score = 0.0 

            # C. Combine Initial Focus Value
            focus_val = (pose_score * self.W_POSE) + (eye_score * self.W_EYES) + (gaze_score * self.W_GAZE)

            # 4. Sleep Logic (> 15s)
            if delta_ear > self.EAR_DROP_THRESH:
                if self.eyes_closed_start_time is None: self.eyes_closed_start_time = time.time()
                elif (time.time() - self.eyes_closed_start_time) > self.SLEEP_LIMIT:
                    focus_val, alert_text = 0.0, "WAKE UP!"
            else: self.eyes_closed_start_time = None

            # 5. Head Down Logic (> 15s)
            if delta_pitch > self.HEAD_DOWN_THRESH:
                if self.head_down_start_time is None: self.head_down_start_time = time.time()
                elif (time.time() - self.head_down_start_time) > 15.0:
                    focus_val, alert_text = 0.0, "HEAD DOWN ALARM!"
            else: self.head_down_start_time = None

            # 6. Stare Logic (> 15s)
            if time_since_blink > self.BLINK_THRESHOLD:
                focus_val, alert_text = 0.0, "PLEASE BLINK!"

            # 7. Final Averaging
            self.focus_history.append(focus_val * 100)
            avg_focus = sum(self.focus_history) / len(self.focus_history)

            if avg_focus > 75: status, alarm_trigger = "FOCUSED", False
            elif avg_focus > 40: status, alarm_trigger = "DISTRACTED", False # Changed to False to prevent alarm on yellow
            else:
                status = alert_text if alert_text else "NOT FOCUSED"
                alarm_trigger = True

            return {
                "face_found": True, "is_calibrated": True, "focus_val": int(avg_focus),
                "status": status, "alarm": alarm_trigger, "blink_timer": int(time_since_blink),
                "gaze_variance": float(gaze_variance)
            }

        else: # NO FACE
            self.eyes_closed_start_time = self.head_down_start_time = None
            if self.is_calibrated:
                self.focus_history.append(0.0)
                avg_focus = sum(self.focus_history) / len(self.focus_history)
                return {"face_found": False, "is_calibrated": True, "focus_val": int(avg_focus), "status": "NO FACE", "alarm": True}
            return {"face_found": False, "is_calibrated": False, "status": "NO FACE", "alarm": False}

    def reset_calibration(self):
        self.__init__()