"""English chapters for the Help screen and the DOCX operation manual (Windows edition).

Mirrors manual_content_win.py (Japanese) chapter for chapter and item for item.
Keep the two files in sync when either changes. Written against v1.1.1 of the app.
"""

MANUAL_VERSION = "1.1.5"
MANUAL_DATE = "2026-09-21"

# Chapter title -> screenshot(s) in docs/images (a list is also accepted).
MANUAL_SCREENSHOTS_WIN_EN: dict = {
    "7. RSSI Measurement": ["screenshot_rssi_win.jpg"],
}

MANUAL_SECTIONS_WIN_EN = [
    ("Credits", [
        ("Credits", "Receiver method and original receiver system design: Shinji Yamazaki (JE1BTA), based on rpi-dvbs2-receiver-gui.\nReceiver stabilization, reacquisition fixes, and application development: Kazuichi Shinjo (JA6FUF/JH1XHX).\nThis application was developed inspired by \"Portsdown\", the DATV transceiver project created by Dave Crump (G8GKQ). We extend our deep gratitude for his pioneering work.\nThe developers accept no liability whatsoever for any damage arising from the use of this program. Use it at your own risk."),
    ]),
    ("Disclaimer", [
        ("No warranty; use at your own risk", "This software is provided \"AS IS\" without warranty of any kind, including any warranty of operation, quality or fitness for a particular purpose. The developers accept no liability for any damage arising from the use of, or inability to use, this software, including damage to equipment, loss of data and radio interference. Use it at your own risk."),
        ("Licensing and compliance with the law", "This software is for amateur-radio DATV (digital ATV) experiments. Transmitting requires a license under the laws of the country or region where you operate (in Japan, an amateur station license). Observe the applicable laws on frequency, transmitter power, emission type and permitted operation (in Japan, the Radio Act and related regulations). Transmitting without a license, or beyond the scope of your license, may violate the law. This software neither checks nor guarantees that the configured frequency, power and modulation comply with the law. You are solely responsible for what you transmit and for the results."),
        ("Handling of equipment", "Wrong TX/RX connections, external amplifier (PA), attenuator or antenna connections, or transmit power settings may damage equipment or interfere with other stations. Check the specifications of your equipment and do this at your own responsibility. In particular, never connect TX directly to RX; use an attenuator of 40 dB or more."),
        ("Third-party software and license", "This software uses and bundles third-party software such as ffmpeg, GNU Radio (radioconda), gr-dvbs2rx and Qt (PyQt5), each under its own license. This software itself is provided under the GNU General Public License v3.0 (GPLv3). See the bundled LICENSE for the full text."),
        ("About behavior", "Behavior may differ depending on your environment, and undiscovered defects may remain."),
    ]),
    ("1. Screen Overview", [
        ("Home screen", "The Home screen is the entrance to every function. It shows 16 cards: Transmit, Receive, Frequency, RSSI Measurement, Symbol Rate, FEC, Modulation, Video Source, Stream Output, RX Gain, TX Power, Config, Diagnostic, Help, App Restart and Exit App. The Frequency card shows the currently set frequency (kHz) and updates automatically when the frequency changes. The Windows edition does not show the Raspberry Pi-only Langstone (SDR transceiver), Presets and Pluto Power cards."),
        ("Common operation", "Operate each screen by clicking its buttons. Use \"Back to Home\" at the top left of a screen (or \"Back to Home\" at the bottom of the TX/RX screens) to return to the Home screen. Besides mouse and touch, text fields accept input from a physical keyboard and the standard Windows IME (the on-screen keyboard of the Pi 5 unit is not included in the Windows edition). The app is shown as a normal Windows window and can be resized."),
        ("Display language", "Switch between \"日本語\" and \"English\" with \"Display Language\" on the Settings screen. The change is applied to every screen immediately, and the choice is kept for the next launch."),
    ]),
    ("2. Startup, Exit and Safety", [
        ("Startup", "Unlike the Pi 5 edition, the app does not restart Pluto automatically at startup; it goes straight to the Home screen (there is no restart wait each time). Power up the Pluto+, connect Ethernet and set its IP address beforehand, then specify the destination in \"Pluto URI\" on the Stream Output screen (the \"Detect\" button can also find it)."),
        ("RF connection caution", "Never connect TX directly to RX. To test indoors, connect TX -> external attenuator of 40 dB or more -> RX."),
        ("Simultaneous TX and RX", "When \"On-device demodulation\" in Settings is OFF, TX and RX cannot run at the same time (exclusive control). Trying to start one while the other is running shows an error dialog. Turn \"On-device demodulation\" ON if you need simultaneous operation. Because one Pluto transmits and receives at the same time, an external attenuator is mandatory (see \"Settings Screen\" below). For safety, on-device demodulation always returns to OFF each time the app starts."),
        ("Exit", "If transmitting or receiving, stop it on its own screen first, then use \"Exit App\" on the Home screen and choose \"Exit\" in the confirmation dialog. \"Exit App\" only ends the Windows app process; it does not shut down the PC. If a PA_Power/PTT controller is configured, the app sends a 12 V power-OFF notification before exiting."),
    ]),
    ("3. Settings Screen", [
        ("Display language", "Choose \"日本語\" or \"English\". The change is applied immediately."),
        ("PA_Power/PTT controller (ESP32)", "Enter the IP address or hostname of the PA_Power/PTT controller (ESP32 + W5500). This is optional; leave it empty to disable the link. When set, PTT follows TX start/stop and the 12 V power (including the Pluto+) is switched ON/OFF automatically at app start/exit. Values containing whitespace or invalid characters are rejected with an error."),
        ("On-device demodulation", "When ON, this PC's own receiver (GNU Radio on radioconda) can demodulate and TX and RX can run at the same time. Only while ON, the TX screen shows \"Go to RX\" and the RX screen shows \"Go to TX\". This is a development/verification mode in which one Pluto transmits and receives at once, so a warning dialog appears when you turn it ON. The Pluto may be damaged unless an external attenuator is inserted. When OFF, TX and RX cannot run at the same time. It always returns to OFF at app startup."),
        ("RX diagnostics (IIO preflight)", "\"Run the IIO preflight test\" is OFF by default. When ON, the app reads a short piece of data from the Pluto's receive side (IIO) at startup or before starting RX to check its health, and warns if it fails. Leave it OFF unless you have a specific reason."),
        ("System date and time", "The Set button in the \"System Date & Time\" field is meant for Raspberry Pi units without an RTC and calls a Linux-only command, so it does not work in the Windows edition (an error is shown). Set the Windows clock from the taskbar clock or Windows Settings -> Time & language."),
        ("About band selection", "The band is selected not on the Settings screen but with \"Band Selection\" on the Frequency screen."),
    ]),
    ("4. Settings Before Transmitting", [
        ("Stream Output (Pluto URI)", "Enter the IP address of the Pluto. As in the Pi 5 edition, the Pluto is connected to the same network as this PC via Ethernet. The \"Detect\" button scans all network adapters of this PC and looks for a device whose Pluto iiod responds (enter it manually if none is found). The destination port is fixed at 8282 on the Pluto side and cannot be changed. \"RX TS port\" (default 4003) and \"Status port\" (default 4002) are receive settings. \"Output Info\" on the right shows the protocol (UDP), Pluto URI, port, MTU and TTL."),
        ("Frequency", "On the Frequency screen, enter the operating frequency in kHz and confirm with \"OK\", or choose the standard frequency of the 1200 MHz, 2400 MHz, 5600 MHz, 10 GHz or 24 GHz band from \"Band Selection\" on the right. The current frequency is shown at the bottom of the screen."),
        ("Symbol Rate", "Set the symbol rate of the transmitted signal. Choose a preset on the left (0.333 to 2.0 Msps) or enter a value in kS/s under Custom Setting. A guideline bandwidth is shown on the screen."),
        ("FEC and Modulation", "Match FEC and modulation between the transmitting and receiving sides. Choose the modulation from QPSK, 8PSK and 16APSK (32APSK cannot be selected because no FEC supports it). The FEC choices are narrowed to combinations that actually work with the selected modulation (QPSK: 1/2, 3/5, 8/9; 8PSK: 3/5, 8/9; 16APSK: 8/9). The FEC screen shows an explanation and the overhead for each code rate, and the DATA/FEC/PARITY frame structure."),
        ("Video Source", "The Video Source screen lets you choose a Windows USB camera or capture device detected by ffmpeg, an image file (png/jpg/jpeg/bmp, sent as a repeating still image), or a test pattern (color bars). The callsign and optional note entered in the \"Callsign\" and \"Note\" fields at the bottom of the screen are burned into the video, with the date and time shown at the bottom right. The selector to the right of each field sets the font size (callsign 36-256 px, note 16-64 px). The callsign color can also be chosen (white, yellow, red, green, blue, cyan, orange, black). They apply to camera video and to an image file (the test pattern already has a callsign drawn into it, so it is not overlaid). The transmitted video is fixed at Full HD (1920x1080); video with a different aspect ratio is fitted with black bars. If no device name is shown, check that ffmpeg is bundled (installed automatically by the installer) and check the camera driver and connection."),
        ("RX Gain", "With AGC (Auto) ON the gain is automatic; with AGC OFF, set the manual gain with the slider. The signal level is also shown."),
        ("TX Power", "Set the output attenuation in the range 0 to -70 dB to match the destination and attenuator. 0 dB is the maximum output; lower values attenuate more."),
    ]),
    ("5. Transmit Screen", [
        ("Reading the TX screen", "The video preview is on the left. On the right are the TX state (\"ON AIR\" is shown while transmitting), frequency, symbol rate, modulation, FEC, attenuation (dB), packet count and frame count. While TX is stopped, the \"Start TX\" button is shown."),
        ("Starting TX", "\"Transmit\" on the Home screen only opens the TX screen. To start transmitting, press \"Start TX\" on the TX screen. If on-device demodulation is OFF and RX is running, \"Cannot Start TX\" is shown, so stop RX first. An unset frequency also causes an error."),
        ("Stopping TX", "While transmitting, press \"Stop TX\", shown in the same position."),
        ("Navigation", "\"Go to RX\" is shown when on-device demodulation is ON. \"Settings\" and \"Back to Home\" are always available."),
    ]),
    ("6. Receive Screen", [
        ("Prerequisites", "Demodulation requires radioconda (GNU Radio + gr-iio + gr-dvbs2rx) to be installed on this PC. It is installed automatically when you use the official installer. If it is not installed, an error saying so is shown when you start RX. For a manual setup, see docs/gr-dvbs2rx-windows/README.md."),
        ("Starting RX", "Match the receive settings to the transmit conditions and press \"Start RX\". While receiving you can check the state (\"Lock\" when locked, \"No Lock\" otherwise), bitrate, packets per second and error count. If on-device demodulation is OFF and TX is running, \"Cannot Start RX\" is shown, so stop TX first."),
        ("Stopping RX", "Press \"Stop RX\" to end reception."),
        ("Volume", "Adjust the playback volume with the volume slider on the RX screen."),
        ("Navigation", "\"Go to TX\" is shown when on-device demodulation is ON. \"Settings\" and \"Back to Home\" are always available."),
    ]),
    ("7. RSSI Measurement", [
        ("What RSSI Measurement does", "It scans a range of frequencies, graphs the received level (RSSI) and quickly identifies the actual frequency of the other station. The center frequency is the value set on the Frequency screen (if it is not set, set it there first)."),
        ("Search conditions", "Choose the search range from ±5 MHz, ±10 MHz and ±20 MHz (the selected range is highlighted in light blue). Enter the step (kHz) with the keypad; specify 1 kHz or more."),
        ("RX gain", "At the lower right of the screen, \"RX Gain\" lets you turn AGC (automatic adjustment) on or off and set the manual gain (0 to 73 dB with the \"−\" and \"+\" buttons; hold to change continuously). The setting is shared with the RX Gain screen and can be changed even while a search is running. Changing the gain changes the RSSI values, so if you change it during a search the current pass is restarted from the beginning. The manual gain cannot be changed while AGC is on."),
        ("Running a search", "Press \"Start Search\" to begin scanning; while it runs, the status shows the current frequency and RSSI. With \"Search Mode\" on the right side of the screen set to \"Repeat\" (default), the scan returns to the start when it reaches the end of the range and repeats until you press \"Stop Search\". With \"Once\", it scans the range one time and stops by itself. If you switch the mode during a search, it takes effect when the current pass finishes. In both modes the search stops when you move to another screen. The graph shows the position of the center frequency as a white line."),
        ("Search result", "Each time one pass of the scan finishes, the \"Strongest frequency\" is updated and shown."),
        ("About automatic TX start", "When \"On-device demodulation\" in Settings is ON, pressing \"Start Search\" automatically starts transmitting (if TX is already running, it is stopped first and restarted with the settings in effect when the search begins). Scanning starts 3 seconds after TX starts (or restarts). This automatic transmission stops on its own when you press \"Stop Search\" or move to another screen. Never connect TX directly to RX; always use an attenuator of 40 dB or more."),
    ]),
    ("8. Basic Operating Procedure", [
        ("TX only", "1) On Home, set Frequency, Symbol Rate, FEC, Modulation, Video Source and TX Power. 2) Press \"Transmit\". 3) Check the video preview on the TX screen. 4) Press \"Start TX\". 5) Press \"Stop TX\" when finished."),
        ("RX only", "1) Match the receive conditions to the transmitting side. 2) If needed, identify the other station's frequency with \"RSSI Measurement\". 3) Press \"Receive\" on Home. 4) Press \"Start RX\" on the RX screen. 5) Check video, audio and statistics. 6) Press \"Stop RX\" when finished."),
        ("RF check", "Confirm the TX -> attenuator -> RX connection, then start reception after starting transmission. With on-device demodulation OFF they cannot run at the same time, so switch it ON in Settings for this check."),
    ]),
    ("9. Help, Diagnostic and App Restart", [
        ("Help", "On the Help screen, choose a chapter from the list on the left to read it. \"Open Operation Manual (Word)\" opens the operation manual (Word) in the current display language."),
        ("Diagnostic", "Diagnostic is used to check connections and processes. \"Full Test\" runs a Pluto restart and connection check, a TX test and an RX test in turn. \"Camera + Audio Test\" checks the sending of camera video and microphone audio. The results do not guarantee the RF environment or antenna performance. It cannot be started while TX/RX is running."),
        ("App Restart", "Stop TX/RX before using \"App Restart\". It stops TX/RX, saves the settings, asks the Pluto to restart, and after reconnecting re-applies the saved radio settings (frequency, symbol rate, etc.). If this takes more than 20 seconds, the wait is abandoned and the Home screen is shown. A warning dialog appears on failure. The PC itself is not restarted."),
    ]),
    ("10. Troubleshooting", [
        ("TX does not start", "Merely moving to the TX screen does not transmit. Press \"Start TX\" and check the video source, Pluto IP, frequency and TX power. If ffmpeg exits immediately several times in a row while using the camera, automatic retry is stopped and an error is shown. In that case check that the camera/microphone is not in use by another app."),
        ("\"Cannot Start TX\" / \"Cannot Start RX\" is shown", "With on-device demodulation OFF, you are trying to start the opposite side (TX while receiving, or RX while transmitting). Stop the running side first, or turn \"On-device demodulation\" ON in Settings."),
        ("Cannot receive / \"Go to RX\" button is missing", "The \"Go to RX\" button is shown only when \"On-device demodulation\" in Settings is ON. If reception itself does not work, check that radioconda (GNU Radio) is installed correctly and follow docs/gr-dvbs2rx-windows/README.md. If the receive process exits immediately several times in a row, automatic retry is stopped and an error with the recent log is shown. Check the power and connection of the Pluto+, restart it if necessary, and try again."),
        ("No camera video", "If the camera is not listed on the Video Source screen, check that ffmpeg is installed (bundled with the official installer), that the camera driver is fine and that no other app is using the camera. You can also switch to the color bars (test pattern) to isolate the transmit chain."),
        ("Pluto is not found", "If \"Detect\" on the Stream Output screen does not find the Pluto, check the Pluto's power and LAN connection, make sure the PC and the Pluto are on the same network, and enter the IP address manually in \"Pluto URI\"."),
        ("Video is black but reception works", "Check the state display and communication statistics on the RX screen, and check the video source and the TX start state."),
        ("About the display scaling", "Even if the Windows display scaling is changed (125%, etc.), the video is adjusted to be drawn correctly inside its frame."),
    ]),
    ("11. Installing and Uninstalling", [
        ("Installer edition", "Running the official ShonanLiteSetup.exe installs the app, ffmpeg, radioconda (GNU Radio) and gr-dvbs2rx for reception in one go. Installing radioconda takes a few minutes. Running a newer installer over an existing installation updates it."),
        ("Uninstall", "Uninstall Shonan_Lite for Windows from Windows Settings -> Apps. radioconda is treated as a separate app, so if you no longer need it, uninstall radioconda from the Apps list as well."),
        ("Running from source", "Setup steps for the GitHub clone and local clone editions are described in README.md for developers."),
    ]),
]
