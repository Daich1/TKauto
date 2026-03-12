"""
Valorant スパイクタイマーアプリ - 配信観戦用

必要パッケージ（pip install）:
    pip install mss customtkinter pynput pyautogui pillow

Windows環境想定。config.json はこのスクリプトと同じディレクトリに配置されます。
"""

import json
import threading
import time
from pathlib import Path

import mss
import customtkinter as ctk
from pynput import keyboard
import pyautogui

# 定数定義
CONFIG_FILENAME = "config.json"
DEFAULT_CONFIG = {
    "x": 960,
    "y": 50,
    "color": {"r": 210, "g": 50, "b": 50},
    "tolerance": 30,
}
MONITOR_INTERVAL = 0.1  # 監視間隔（秒）
UI_UPDATE_INTERVAL_MS = 20  # UI更新間隔（ミリ秒）
COUNTDOWN_SECONDS = 45.0
RESET_DELAY_SECONDS = 3.0  # 0秒到達後、リセットまでの待機
WATCH_REGION_SIZE = 10  # 監視する矩形サイズ（中心からの半辺）
HOTKEY_SAVE = keyboard.Key.f12

# フェーズ別背景色
PHASE_COLORS = {
    1: "#2B2B2B",   # ダークグレー (待機 & 45.00~20.00)
    2: "#1F51FF",   # 青色 (19.99~7.00)
    3: "#FFD700",   # 黄色 (6.99~3.50)
    4: "#FF3131",   # 赤色 (3.49~0.00)
}


def load_config(base_dir: Path) -> dict:
    """config.json を読み込み、存在しないまたは破損している場合はデフォルトで作成"""
    config_path = base_dir / CONFIG_FILENAME
    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 必要キーの検証
                if all(k in data for k in ["x", "y", "color", "tolerance"]):
                    color = data["color"]
                    if all(c in color for c in ["r", "g", "b"]):
                        return data
    except (json.JSONDecodeError, KeyError):
        pass

    # デフォルトで新規作成
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
    return DEFAULT_CONFIG.copy()


def save_config(base_dir: Path, config: dict) -> bool:
    """config.json に設定を保存"""
    try:
        config_path = base_dir / CONFIG_FILENAME
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def color_matches(pixel_rgb: tuple, target: dict, tolerance: int) -> bool:
    """ピクセルが目標色±toleranceの範囲内か判定"""
    r, g, b = pixel_rgb
    tr, tg, tb = target["r"], target["g"], target["b"]
    return (
        abs(r - tr) <= tolerance
        and abs(g - tg) <= tolerance
        and abs(b - tb) <= tolerance
    )


def get_phase(seconds: float) -> int:
    """残り秒数からフェーズ番号を返す"""
    if seconds >= 20.0 or seconds < 0:
        return 1
    if seconds >= 7.0:
        return 2
    if seconds >= 3.5:
        return 3
    return 4


class SpikeTimerApp(ctk.CTk):
    """スパイクタイマーアプリのメインウィンドウ"""

    def __init__(self):
        super().__init__()
        self.base_dir = Path(__file__).resolve().parent
        self.config_data = load_config(self.base_dir)

        self.title("Valorant スパイクタイマー")
        self.geometry("400x200")
        self.resizable(True, True)

        # 状態変数
        self.remaining_seconds = COUNTDOWN_SECONDS
        self.is_counting = False
        self.is_locked = False  # 二重起動防止用（検出後ロック）
        self.countdown_start_time = None
        self.monitor_thread = None
        self.monitor_running = False
        self.show_saved_feedback = False
        self.saved_feedback_end_time = 0.0
        self.config_lock = threading.Lock()

        self._setup_ui()
        self._start_monitor_thread()
        self._start_keyboard_listener()
        self._start_ui_update_loop()

    def _setup_ui(self):
        """UIを構築"""
        self.configure(fg_color=PHASE_COLORS[1])

        self.timer_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.timer_frame.pack(expand=True, fill="both", padx=20, pady=20)

        self.timer_label = ctk.CTkLabel(
            self.timer_frame,
            text="45.00",
            font=ctk.CTkFont(size=72, weight="bold"),
            text_color="white",
        )
        self.timer_label.pack(expand=True)

        self.status_label = ctk.CTkLabel(
            self.timer_frame,
            text="待機中 - F12で座標・色をキャリブレーション",
            font=ctk.CTkFont(size=12),
            text_color="white",
        )
        self.status_label.pack(pady=(0, 10))

    def _update_background_for_phase(self, phase: int):
        """フェーズに応じて背景色を更新"""
        self.configure(fg_color=PHASE_COLORS[phase])
        self.timer_frame.configure(fg_color=PHASE_COLORS[phase])

    def _start_monitor_thread(self):
        """画面監視スレッドを開始"""
        self.monitor_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _monitor_loop(self):
        """0.1秒間隔で画面を監視し、色条件に合致したらカウントダウン開始"""
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # メインモニター
            while self.monitor_running:
                try:
                    with self.config_lock:
                        x = self.config_data["x"]
                        y = self.config_data["y"]
                        color = self.config_data["color"].copy()
                        tolerance = self.config_data["tolerance"]

                    # 10x10の矩形（中心を基準）
                    half = WATCH_REGION_SIZE // 2
                    left = max(0, x - half)
                    top = max(0, y - half)
                    width = min(WATCH_REGION_SIZE, monitor["width"] - left)
                    height = min(WATCH_REGION_SIZE, monitor["height"] - top)

                    region = {"left": left, "top": top, "width": width, "height": height}
                    screenshot = sct.grab(region)

                    # ピクセルデータをチェック (BGRA形式)
                    found = False
                    for py in range(screenshot.height):
                        for px in range(screenshot.width):
                            idx = (py * screenshot.width + px) * 4
                            b = screenshot.raw[idx]
                            g = screenshot.raw[idx + 1]
                            r = screenshot.raw[idx + 2]
                            if color_matches((r, g, b), color, tolerance):
                                found = True
                                break
                        if found:
                            break

                    if found and not self.is_counting and not self.is_locked:
                        self.is_counting = True
                        self.is_locked = True
                        self.countdown_start_time = time.perf_counter()
                        self.remaining_seconds = COUNTDOWN_SECONDS

                except Exception:
                    pass

                time.sleep(MONITOR_INTERVAL)

    def _start_keyboard_listener(self):
        """F12ホットキーでキャリブレーション"""
        def on_press(key):
            if key == HOTKEY_SAVE:
                threading.Thread(target=self._do_calibration, daemon=True).start()

        self._keyboard_listener = keyboard.Listener(on_press=on_press)
        self._keyboard_listener.start()

    def _do_calibration(self):
        """マウス座標とピクセル色を取得し、config.jsonに保存"""
        x, y = pyautogui.position()
        try:
            pixel = pyautogui.pixel(x, y)
            r, g, b = pixel
        except OSError:
            return

        new_config = {
            "x": x,
            "y": y,
            "color": {"r": r, "g": g, "b": b},
            "tolerance": self.config_data.get("tolerance", DEFAULT_CONFIG["tolerance"]),
        }

        with self.config_lock:
            self.config_data = new_config

        if save_config(self.base_dir, new_config):
            self.show_saved_feedback = True
            self.saved_feedback_end_time = time.perf_counter() + 1.0

    def _start_ui_update_loop(self):
        """UI更新ループ（10〜30ms間隔）"""
        self._ui_update_tick()

    def _ui_update_tick(self):
        """1ティック分のUI更新"""
        now = time.perf_counter()

        # SAVED! フィードバック表示
        if self.show_saved_feedback:
            if now < self.saved_feedback_end_time:
                self.timer_label.configure(text="SAVED!")
            else:
                self.show_saved_feedback = False
                self.timer_label.configure(text=f"{self.remaining_seconds:.2f}")
            self.after(UI_UPDATE_INTERVAL_MS, self._ui_update_tick)
            return

        if self.is_counting:
            elapsed = now - self.countdown_start_time
            self.remaining_seconds = max(0.0, COUNTDOWN_SECONDS - elapsed)

            display_text = f"{self.remaining_seconds:.2f}"
            self.timer_label.configure(text=display_text)

            phase = get_phase(self.remaining_seconds)
            self._update_background_for_phase(phase)

            if self.remaining_seconds <= 0.0:
                # 0秒到達：3秒待ってリセット
                self.after(
                    int(RESET_DELAY_SECONDS * 1000),
                    self._reset_to_waiting,
                )
                self.is_counting = False

        else:
            # 待機中
            display_text = f"{self.remaining_seconds:.2f}"
            self.timer_label.configure(text=display_text)
            self._update_background_for_phase(1)

        self.after(UI_UPDATE_INTERVAL_MS, self._ui_update_tick)

    def _reset_to_waiting(self):
        """待機状態にリセット"""
        self.remaining_seconds = COUNTDOWN_SECONDS
        self.is_locked = False
        self.is_counting = False
        self.timer_label.configure(text="45.00")
        self._update_background_for_phase(1)

    def on_closing(self):
        """終了処理"""
        self.monitor_running = False
        self.destroy()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = SpikeTimerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
