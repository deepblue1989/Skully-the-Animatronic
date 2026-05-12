#include <LiquidCrystal.h>
#include <Servo.h>

// 1. CONSTANTS & PIN MAPPING
const int rs = 12, en = 11, d4 = 5, d5 = 4, d6 = 3, d7 = 2;
LiquidCrystal lcd(rs, en, d4, d5, d6, d7);

const int servoPin = 10;
const int backlightPin = 8; 
const int CLOSED_ANGLE = 180; // Added missing constant
Servo jawServo;

// 2. STATE VARIABLES
String currentEmotion = "NEUTRAL";
unsigned long lastSerialTime = 0;
const unsigned long timeoutLimit = 3000; 
bool isConnected = false;

// 3. HELPER FUNCTIONS (Defined before they are used or prototype-ready)
void updateEmotionLine() {
  lcd.setCursor(0, 1);
  lcd.print("EMO: ");
  lcd.print(currentEmotion);
  lcd.print("        "); 
}

void displayStatus(String status, String emotion) {
  lcd.setCursor(0, 0);
  lcd.print("STAT: ");
  lcd.print(status);
  lcd.print("        "); 
  updateEmotionLine();
}

// 4. MAIN SETUP
void setup() {
  Serial.begin(115200);
  pinMode(backlightPin, OUTPUT);
  digitalWrite(backlightPin, LOW); // Backlight ON

  jawServo.attach(servoPin);
  jawServo.write(CLOSED_ANGLE); 

  lcd.begin(16, 2);
  
  // Initialize as Offline
  isConnected = false;
  displayStatus("OFFLINE", "NONE");
}

// 5. MAIN LOOP
void loop() {
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    
    if (!isConnected) {
      isConnected = true;
    }
    lastSerialTime = millis();

    if (input == "THINK_START") {
      displayStatus("THINKING", currentEmotion);
    } 
    else if (input == "SPEAK_START") {
      displayStatus("SPEAKING", currentEmotion);
    }
    else if (input == "LISTEN_START") {
      displayStatus("LISTENING", currentEmotion);
    }
    else if (input.startsWith("E:")) {
      currentEmotion = input.substring(2);
      updateEmotionLine();
    }
    else if (input.length() > 0 && isDigit(input[0])) {
      int angle = input.toInt();
      jawServo.write(angle);
    }
  }

  // Heartbeat/Timeout Logic
  if (isConnected && (millis() - lastSerialTime > timeoutLimit)) {
    isConnected = false;
    currentEmotion = "NEUTRAL";
    displayStatus("OFFLINE", "NONE");
    jawServo.write(CLOSED_ANGLE);
  }
}