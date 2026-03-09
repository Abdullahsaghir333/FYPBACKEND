import cv2
import mediapipe as mp
import numpy as np
import time
import math
from collections import deque
import pygame

# ---------------------------------------------------------------------------
# INITIAL SETUP
# ---------------------------------------------------------------------------
pygame.mixer.init()
try:
    pygame.mixer.music.load("1208.mp3") 
except pygame.error:
    print("Error: Audio file '1208.mp3' not found! Audio features disabled.")

# Thresholds 
PITCH_TOLERANCE = 25.0  
HEAD_DOWN_THRESH = 45.0 
YAW_TOLERANCE = 20.0    
EAR_DROP_THRESH = 0.04  
BLINK_THRESHOLD = 15.0  
SLEEP_LIMIT = 15.0 
GAZE_MOVE_THRESH = 0.005 # Sensitivity for eye movement (Lower = easier to detect reading)

# Weights
W_POSE = 0.4
W_EYES = 0.3
W_GAZE = 0.3  

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------
def get_head_pose(landmarks, img_w, img_h):
    face_3d = np.array([
        [0.0, 0.0, 0.0],            # Nose tip
        [0.0, 330.0, -65.0],        # Chin
        [-225.0, -170.0, -135.0],   # Left Eye Left Corner
        [225.0, -170.0, -135.0],    # Right Eye Right Corner
        [-150.0, 150.0, -125.0],    # Left Mouth Corner
        [150.0, 150.0, -125.0]      # Right Mouth Corner
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
    rmat, jac = cv2.Rodrigues(rot_vec)
    angles, mtxR, mtxQ, Qx, Qy, Qz = cv2.RQDecomp3x3(rmat)

    return angles[0], angles[1], angles[2]

def calculate_ear(landmarks, indices):
    v1 = np.linalg.norm(np.array([landmarks[indices[1]].x, landmarks[indices[1]].y]) - 
                        np.array([landmarks[indices[5]].x, landmarks[indices[5]].y]))
    v2 = np.linalg.norm(np.array([landmarks[indices[2]].x, landmarks[indices[2]].y]) - 
                        np.array([landmarks[indices[4]].x, landmarks[indices[4]].y]))
    h = np.linalg.norm(np.array([landmarks[indices[0]].x, landmarks[indices[0]].y]) - 
                       np.array([landmarks[indices[3]].x, landmarks[indices[3]].y]))
    return (v1 + v2) / (2.0 * h)

def get_gaze_score(landmarks):
    # This just checks if eyes are centered
    L_left = landmarks[33].x
    L_right = landmarks[133].x
    L_iris = landmarks[468].x
    L_center = (L_left + L_right) / 2
    L_dist = abs(L_iris - L_center)
    
    R_left = landmarks[362].x
    R_right = landmarks[263].x
    R_iris = landmarks[473].x
    R_center = (R_left + R_right) / 2
    R_dist = abs(R_iris - R_center)
    
    avg_dist = (L_dist + R_dist) / 2
    
    if avg_dist < 0.004: return 1.0  
    elif avg_dist < 0.008: return 0.5 
    else: return 0.0 

# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
cap = cv2.VideoCapture(0)
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

is_calibrated = False
calibration_frames = 0
MAX_CALIB_FRAMES = 100
baseline_pitch = 0
baseline_yaw = 0
baseline_ear = 0

last_blink_time = time.time()
eyes_closed_start_time = None 
focus_history = deque(maxlen=20)
gaze_history = deque(maxlen=30)
# --- Ensure these are initialized before your while loop ---
head_down_start_time = None
eyes_closed_start_time = None

while True:
    ret, frame = cap.read()
    if not ret: break
    h, w, c = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)

    focus_val = 0.0
    face_found = False

    # 1. FACE DETECTED
    if results.multi_face_landmarks:
        face_found = True
        lm = results.multi_face_landmarks[0].landmark

        pitch, yaw, roll = get_head_pose(lm, w, h)
        ear = (calculate_ear(lm, LEFT_EYE) + calculate_ear(lm, RIGHT_EYE)) / 2.0
        gaze_score = get_gaze_score(lm) 

        # --- PHASE 1: CALIBRATION ---
        if not is_calibrated:
            calibration_frames += 1
            baseline_pitch += pitch
            baseline_yaw += yaw
            baseline_ear += ear
            
            cv2.putText(frame, "CALIBRATING...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
            cv2.rectangle(frame, (50, 150), (50 + int(calibration_frames*3), 180), (255, 0, 0), -1)

            if calibration_frames >= MAX_CALIB_FRAMES:
                baseline_pitch /= MAX_CALIB_FRAMES
                baseline_yaw /= MAX_CALIB_FRAMES
                baseline_ear /= MAX_CALIB_FRAMES
                is_calibrated = True
                last_blink_time = time.time() 
                print("Calibration Done.")
            
            cv2.imshow("Focus Monitor", frame)
            if cv2.waitKey(1) == ord('q'): break
            continue 

        # --- PHASE 2: MONITORING ---
        else:
            # BLINK DETECTION (Physical blink)
            if (baseline_ear - ear) > 0.03: 
                last_blink_time = time.time() 
            
            # EYE MOVEMENT (Gaze) DETECTION
            current_gaze_val = (lm[468].x + lm[473].x) / 2.0 
            gaze_history.append(current_gaze_val)
            
            if len(gaze_history) > 10:
                gaze_variance = np.var(list(gaze_history)) * 10000 
            else:
                gaze_variance = 0.0

            # UPDATED: If eyeball is moving, reset blink timer to 0
            if gaze_variance > GAZE_MOVE_THRESH:
                last_blink_time = time.time()

            time_since_blink = time.time() - last_blink_time

            # CALCULATE BASE SCORES
            delta_pitch = abs(pitch - baseline_pitch)
            delta_yaw = abs(yaw - baseline_yaw)
            delta_ear = baseline_ear - ear 

            # A. Head Pose Score
            if delta_pitch < PITCH_TOLERANCE and delta_yaw < YAW_TOLERANCE:
                pose_score = 1.0
            elif delta_pitch < PITCH_TOLERANCE*1.5 and delta_yaw < YAW_TOLERANCE*1.5:
                pose_score = 0.5
            else:
                pose_score = 0.0

            # B. Eye Openness Score
            if delta_ear < EAR_DROP_THRESH: eye_score = 1.0 
            elif delta_ear < EAR_DROP_THRESH + 0.05: eye_score = 0.5 
            else: eye_score = 0.0 

            # C. Combine Initial Focus Value
            focus_val = (pose_score * W_POSE) + (eye_score * W_EYES) + (gaze_score * W_GAZE)
            
            # --- OVERRIDE: SLEEP LOGIC (Eyes closed > 15s) ---
            if delta_ear > EAR_DROP_THRESH: 
                if eyes_closed_start_time is None:
                    eyes_closed_start_time = time.time()
                elif (time.time() - eyes_closed_start_time) > SLEEP_LIMIT:
                    focus_val = 0.0 # Force alarm
                    cv2.putText(frame, "WAKE UP!", (w//2 - 100, h//2 - 100), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0,0,255), 4)
            else:
                eyes_closed_start_time = None 

            # --- OVERRIDE: HEAD DOWN LOGIC (> 15s) ---
            if delta_pitch > HEAD_DOWN_THRESH:
                if head_down_start_time is None:
                    head_down_start_time = time.time()
                elif (time.time() - head_down_start_time) > 15.0:
                    focus_val = 0.0 # Force alarm
                    cv2.putText(frame, "HEAD DOWN ALARM!", (w//2 - 150, h//2 + 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,0,255), 3)
            else:
                head_down_start_time = None

            # --- OVERRIDE: STARE DETECTION ---
            if time_since_blink > BLINK_THRESHOLD:
                focus_val = 0.0 
                cv2.putText(frame, "PLEASE BLINK!", (w//2 - 100, h//2), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,0,255), 3)

            # Debug Info
            cv2.putText(frame, f"Blink Timer: {int(time_since_blink)}s", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
            cv2.putText(frame, f"Eye Move: {gaze_variance:.4f}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)

    # 2. NO FACE DETECTED
    else:
        if is_calibrated:
            focus_val = 0.0 
            cv2.putText(frame, "NO FACE DETECTED", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            eyes_closed_start_time = None
            head_down_start_time = None

    # 3. ALARM TRIGGER LOGIC
    if is_calibrated:
        focus_history.append(focus_val * 100)
        avg_focus = sum(focus_history) / len(focus_history)
        
        if avg_focus > 75:
            status = "FOCUSED"
            col = (0, 255, 0)
            if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
        elif avg_focus > 40:
            status = "DISTRACTED"
            col = (0, 255, 255)
            if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
        else:
            status = "NOT FOCUSED"
            col = (0, 0, 255)
            if not pygame.mixer.music.get_busy():
                try: pygame.mixer.music.play(-1)
                except: pass

        # UI
        cv2.putText(frame, f"{status} ({int(avg_focus)}%)", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, col, 2)
        cv2.putText(frame, "Press 'c' to recalibrate", (w-250, h-20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100,100,100), 1)

    cv2.imshow("Focus Monitor", frame)
    key = cv2.waitKey(1)
    if key == ord('q'): break
    if key == ord('c'): 
        is_calibrated = False
        calibration_frames = 0
        baseline_pitch = 0
        baseline_yaw = 0
        baseline_ear = 0
        focus_history.clear()
        gaze_history.clear()
        eyes_closed_start_time = None
        head_down_start_time = Nonecap.release()
cv2.destroyAllWindows()