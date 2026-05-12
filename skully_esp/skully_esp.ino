// Left Side Pins: GPIO 14 (R), 12 (G), 13 (B)
const int redPin = 14;
const int greenPin = 12;
const int bluePin = 13;

int targetR, targetG, targetB;
int currentR, currentG, currentB;

void setup() {
  Serial.begin(115200);
  pinMode(redPin, OUTPUT);
  pinMode(greenPin, OUTPUT);
  pinMode(bluePin, OUTPUT);
}

void loop() {
  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    int first = data.indexOf(',');
    int second = data.lastIndexOf(',');
    if (first != -1) {
      targetR = data.substring(0, first).toInt();
      targetG = data.substring(first + 1, second).toInt();
      targetB = data.substring(second + 1).toInt();
    }
  }

  // Smooth Fading Logic
  if (currentR != targetR) currentR += (targetR > currentR) ? 1 : -1;
  if (currentG != targetG) currentG += (targetG > currentG) ? 1 : -1;
  if (currentB != targetB) currentB += (targetB > currentB) ? 1 : -1;

  analogWrite(redPin, currentR);
  analogWrite(greenPin, currentG);
  analogWrite(bluePin, currentB);
  
  delay(5); // Adjust for fade speed
}