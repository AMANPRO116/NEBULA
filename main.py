import time
import threading

import cv2
import requests
import speech_recognition as sr


# ============================================================
# CONFIG
# ============================================================

BOARD_ETH_IP = "192.168.50.20"
BOARD_WIFI_IP = "10.158.242.219"

BOARD_PORT = 5000

ETH_TIMEOUT = 2
WIFI_TIMEOUT = 4

CAMERA_INDEX = 0

LOOK_UPDATE_INTERVAL = 0.5

LOOK_CHANGE_THRESHOLD = 5


# ============================================================
# STATE
# ============================================================

recognizer = sr.Recognizer()

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades +
    "haarcascade_frontalface_default.xml"
)

last_host = BOARD_ETH_IP


# ============================================================
# NETWORK
# ============================================================

def post(endpoint, payload, timeout=None):

    global last_host

    hosts = [
        last_host
    ]

    for host in [
        BOARD_ETH_IP,
        BOARD_WIFI_IP
    ]:

        if host not in hosts:
            hosts.append(host)

    for host in hosts:

        request_timeout = (
            ETH_TIMEOUT
            if host == BOARD_ETH_IP
            else WIFI_TIMEOUT
        )

        if timeout is not None:
            request_timeout = timeout

        try:

            url = (
                f"http://{host}:"
                f"{BOARD_PORT}{endpoint}"
            )

            response = requests.post(
                url,
                json=payload,
                timeout=request_timeout
            )

            response.raise_for_status()

            last_host = host

            print(
                f"[NETWORK] {endpoint} OK "
                f"via {host}"
            )

            return response

        except requests.RequestException as e:

            print(
                f"[NETWORK] {endpoint} failed "
                f"via {host}: {e}"
            )

    return None


# ============================================================
# HEALTH CHECK
# ============================================================

def connect_to_robot():

    global last_host

    for host in [
        BOARD_ETH_IP,
        BOARD_WIFI_IP
    ]:

        try:

            timeout = (
                ETH_TIMEOUT
                if host == BOARD_ETH_IP
                else WIFI_TIMEOUT
            )

            response = requests.get(
                f"http://{host}:{BOARD_PORT}/health",
                timeout=timeout
            )

            response.raise_for_status()

            last_host = host

            print(
                "[NETWORK] Connected to "
                f"NEUROFORGE via {host}"
            )

            return True

        except requests.RequestException:

            print(
                f"[NETWORK] Cannot reach {host}"
            )

    return False


# ============================================================
# CAMERA
# ============================================================

def camera_loop():

    cap = cv2.VideoCapture(
        CAMERA_INDEX
    )

    if not cap.isOpened():

        print(
            "[CAMERA] Cannot open camera"
        )

        return

    was_present = False

    last_look_time = 0

    last_x = None
    last_y = None

    print(
        "[CAMERA] Running - press Q to quit"
    )

    while True:

        ok, frame = cap.read()

        if not ok:
            continue

        gray = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2GRAY
        )

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=5,
            minSize=(80, 80)
        )

        present = len(faces) > 0

        # ----------------------------------------
        # PRESENCE
        # Send ONLY when state changes
        # ----------------------------------------

        if present != was_present:

            post(
                "/presence",
                {
                    "present": present
                }
            )

            was_present = present

        # ----------------------------------------
        # FACE TRACKING
        # ----------------------------------------

        if present:

            x, y, w, h = max(
                faces,
                key=lambda f: f[2] * f[3]
            )

            cx = x + w // 2
            cy = y + h // 2

            frame_h, frame_w = (
                frame.shape[:2]
            )

            x_pct = int(
                cx / frame_w * 100
            )

            y_pct = int(
                cy / frame_h * 100
            )

            now = time.time()

            moved = (
                last_x is None
                or abs(x_pct - last_x)
                >= LOOK_CHANGE_THRESHOLD
                or abs(y_pct - last_y)
                >= LOOK_CHANGE_THRESHOLD
            )

            if (
                moved
                and now - last_look_time
                >= LOOK_UPDATE_INTERVAL
            ):

                post(
                    "/look",
                    {
                        "x": x_pct,
                        "y": y_pct
                    }
                )

                last_x = x_pct
                last_y = y_pct
                last_look_time = now

            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2
            )

        # ----------------------------------------
        # SHOW CAMERA
        # ----------------------------------------

        cv2.imshow(
            "NEUROFORGE CAMERA - Q to quit",
            frame
        )

        if (
            cv2.waitKey(1) & 0xFF
            == ord("q")
        ):

            break

    cap.release()

    cv2.destroyAllWindows()


# ============================================================
# MICROPHONE
# ============================================================

def mic_loop():

    try:

        with sr.Microphone() as source:

            print(
                "[MIC] Calibrating..."
            )

            recognizer.adjust_for_ambient_noise(
                source,
                duration=1
            )

            print(
                "[MIC] READY - Speak to NEUROFORGE"
            )

            while True:

                try:

                    audio = recognizer.listen(
                        source,
                        timeout=None,
                        phrase_time_limit=10
                    )

                    print(
                        "[MIC] Processing..."
                    )

                    text = recognizer.recognize_google(
                        audio
                    )

                    text = text.strip()

                    if not text:
                        continue

                    print(
                        f"[MIC] HEARD: {text}"
                    )

                    # IMPORTANT:
                    # SEND TO /chat
                    # NOT /speak

                    response = post(
                        "/chat",
                        {
                            "message": text
                        },
                        timeout=90
                    )

                    if response is not None:

                        try:

                            print(
                                "[CHAT RESPONSE]",
                                response.json()
                            )

                        except Exception:

                            print(
                                "[CHAT RESPONSE]",
                                response.text
                            )

                except sr.UnknownValueError:

                    print(
                        "[MIC] Could not understand"
                    )

                except sr.RequestError as e:

                    print(
                        "[MIC ERROR]",
                        e
                    )

                except Exception as e:

                    print(
                        "[MIC ERROR]",
                        e
                    )

    except Exception as e:

        print(
            "[MIC STARTUP ERROR]",
            e
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("NEUROFORGE LAPTOP CLIENT")
    print("=" * 60)

    if not connect_to_robot():

        print(
            "[WARNING] Robot is not reachable."
        )

        print(
            "[WARNING] Check UNO Q main.py."
        )

    mic_thread = threading.Thread(
        target=mic_loop,
        daemon=True
    )

    mic_thread.start()

    camera_loop()


if __name__ == "__main__":

    main()
