/*
 * dobi_gimbal.ino -- dobi pan-tilt gimbal Arduino bridge.
 *
 * Hardware (both axes are 270deg MG995 servos):
 *   Pan  : D9   front = 150 (horn re-mounted), left = toward 320, right = toward 90,
 *               home 150, safe 90..320.
 *   Tilt : D10  horn re-mounted + re-calibrated 2026-05-30. horizontal (level) = 115,
 *               home 115, down toward -45, up toward 240, safe -45..240.
 *
 * The pan/tilt safe ranges extend well past the nominal 0..270 (pan to 320,
 * tilt down to -45) to reach the servos' full physical travel for the dock pose
 * (the servos were confirmed to respond past the nominal 500..2500us window).
 * The deg<->us SCALE is anchored at the nominal 0..270 <-> 500..2500us and is NOT
 * changed, so the front/horizontal calibration stays valid; extended targets are
 * extrapolated on that same scale and hard-clamped to a wider hw pulse window.
 *
 * Serial 115200 8N1, line ASCII.
 *   PC -> Arduino : "P<int>,T<int>\n"  ABSOLUTE servo-deg target
 *                   "R\n"              reset to home
 *   Arduino -> PC : "S<int>,<int>\n"   current absolute servo deg (~50Hz)
 *                   "B\n"              boot banner
 *
 * The host (gimbal_bridge_node) also clamps to the safe range; the limits below
 * are an independent firmware hard backstop. Watch for servo strain near the
 * extended ends -- holding against a mechanical hard stop stalls the MG995.
 *
 * Motion is ramped RAMP_STEP deg per TICK_MS (default 1 deg / 20 ms = 50 deg/s).
 * Lower RAMP_STEP or raise TICK_MS for gentler motion / less overshoot.
 */
#include <Servo.h>

const int PIN_PAN  = 9;
const int PIN_TILT = 10;

// absolute servo-deg safe range (hard backstop)
const int PAN_MIN   = 90;
const int PAN_MAX   = 320;
const int PAN_HOME  = 150;
const int TILT_MIN  = -45;
const int TILT_MAX  = 240;
const int TILT_HOME = 115;

// deg<->us SCALE reference (do NOT change -- this defines the calibration).
const int DEG_RANGE  = 270;
const int US_MAP_MIN = 500;
const int US_MAP_MAX = 2500;
// writeMicroseconds hardware window -- wider than the map endpoints so extended
// (extrapolated) deg targets can drive past 500..2500us toward the mechanical ends.
const int US_HW_MIN = 150;
const int US_HW_MAX = 2900;

const unsigned long TICK_MS = 20;   // 50 Hz tick
const int RAMP_STEP = 1;            // deg per tick

Servo panServo;
Servo tiltServo;

int curPan  = PAN_HOME;
int curTilt = TILT_HOME;
int tgtPan  = PAN_HOME;
int tgtTilt = TILT_HOME;

String buf = "";
unsigned long lastTickMs = 0;

int clampi(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

int degToUs(int deg) {
  // linear scale anchored at nominal 0..270 <-> 500..2500 (calibration),
  // extrapolated for extended targets, then hard-clamped to the hw pulse window.
  long us = (long)US_MAP_MIN + (long)(US_MAP_MAX - US_MAP_MIN) * deg / DEG_RANGE;
  if (us < US_HW_MIN) us = US_HW_MIN;
  if (us > US_HW_MAX) us = US_HW_MAX;
  return (int)us;
}

void writePan(int deg)  { panServo.writeMicroseconds(degToUs(deg)); }
void writeTilt(int deg) { tiltServo.writeMicroseconds(degToUs(deg)); }

void applyCommand(String line) {
  line.trim();
  if (line.length() == 0) return;
  if (line == "R") {
    tgtPan  = PAN_HOME;
    tgtTilt = TILT_HOME;
    return;
  }
  if (line.charAt(0) != 'P') return;
  int comma = line.indexOf(',');
  if (comma < 0) return;
  int tIdx = line.indexOf('T', comma);
  if (tIdx < 0) return;
  int p = line.substring(1, comma).toInt();
  int t = line.substring(tIdx + 1).toInt();
  tgtPan  = clampi(p, PAN_MIN, PAN_MAX);
  tgtTilt = clampi(t, TILT_MIN, TILT_MAX);
}

void setup() {
  Serial.begin(115200);
  // Set the home target BEFORE attach so each servo holds home from its first
  // pulse instead of jerking to the library default. On the AVR Servo lib the
  // servo index is assigned in the constructor, so a write before attach is
  // stored and used once attach starts pulsing.
  writePan(curPan);
  panServo.attach(PIN_PAN, US_HW_MIN, US_HW_MAX);
  writeTilt(curTilt);
  tiltServo.attach(PIN_TILT, US_HW_MIN, US_HW_MAX);
  Serial.println("B");
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') { applyCommand(buf); buf = ""; }
    else if (c != '\r') buf += c;
  }

  unsigned long now = millis();
  if (now - lastTickMs < TICK_MS) return;
  lastTickMs = now;

  curPan  += constrain(tgtPan  - curPan,  -RAMP_STEP, RAMP_STEP);
  curTilt += constrain(tgtTilt - curTilt, -RAMP_STEP, RAMP_STEP);
  writePan(curPan);
  writeTilt(curTilt);

  Serial.print('S');
  Serial.print(curPan);
  Serial.print(',');
  Serial.println(curTilt);
}
