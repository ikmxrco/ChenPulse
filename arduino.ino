
#include <DHT.h>

// ================ PIN CONFIGURATION ================

#define TRIG_PIN 9
#define ECHO_PIN 10
#define DHT_PIN 2
#define DHT_TYPE DHT11

#define RED_PIN 3
#define GREEN_PIN 5
#define BLUE_PIN 6
#define BUZZER_PIN 8

DHT dht(DHT_PIN, DHT_TYPE);

// ================ TIMING ================

const unsigned long SENSOR_INTERVAL = 500;
const unsigned long DHT_INTERVAL = 2000;
const unsigned long DASHBOARD_TIMEOUT = 5000;

// ================ VARIABLES ================

float temperature = NAN;
float humidity = NAN;
float distanceCM = -1;

float waterPercentage = 0;
float rawWaterPercentage = 0;

bool hasPercentageReading = false;

bool monitoringUnlocked = false;

unsigned long lastDashboardMessage = 0;
unsigned long lastSensorRead = 0;
unsigned long lastDHTRead = 0;
unsigned long lastBeepChange = 0;

bool buzzerState = false;

String inputCommand = "";

// ================ LED STATES ================

enum LEDState {
  LED_OFF,
  LED_GREEN,
  LED_YELLOW,
  LED_RED
};

LEDState currentLEDState = LED_OFF;

// ================ ULTRASONIC SENSOR ================

float readDistance() {

  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration = pulseIn(
    ECHO_PIN,
    HIGH,
    25000
  );

  if (duration == 0) return -1;

  float distance = duration * 0.0343 / 2.0;

  if (distance < 2 || distance > 400) return -1;

  return distance;
}

// ================ FILTERED DISTANCE ================

float readFilteredDistance() {

  const int SAMPLE_COUNT = 5;

  float samples[SAMPLE_COUNT];
  int validCount = 0;

  for (int i = 0; i < SAMPLE_COUNT; i++) {

    float reading = readDistance();

    if (reading > 0) {
      samples[validCount++] = reading;
    }

    delay(25);
  }

  if (validCount == 0) return -1;

  // Sort readings from smallest to largest.

  for (int i = 0; i < validCount - 1; i++) {

    for (int j = i + 1; j < validCount; j++) {

      if (samples[j] < samples[i]) {

        float temp = samples[i];
        samples[i] = samples[j];
        samples[j] = temp;
      }
    }
  }

  // Return the median reading.

  return samples[validCount / 2];
}

// ================ RGB LED ================

void setRGB(int red, int green, int blue) {

  analogWrite(RED_PIN, red);
  analogWrite(GREEN_PIN, green);
  analogWrite(BLUE_PIN, blue);
}


void turnOffOutputs() {

  setRGB(0, 0, 0);

  digitalWrite(BUZZER_PIN, LOW);

  buzzerState = false;

  currentLEDState = LED_OFF;

  waterPercentage = 0;
  rawWaterPercentage = 0;

  hasPercentageReading = false;
}

// ================ WATER PERCENTAGE FILTER ================

void updateFilteredPercentage(float incomingPercentage) {

  rawWaterPercentage = constrain(
    incomingPercentage,
    0.0,
    100.0
  );

  // First reading initializes the filter.

  if (!hasPercentageReading) {

    waterPercentage = rawWaterPercentage;

    hasPercentageReading = true;

  } else {

    // Exponential smoothing.
    // Higher alpha = faster response.
    // Lower alpha = smoother response.

    const float FILTER_ALPHA = 0.35;

    waterPercentage =
      (FILTER_ALPHA * rawWaterPercentage) +
      ((1.0 - FILTER_ALPHA) * waterPercentage);
  }

  waterPercentage = constrain(
    waterPercentage,
    0.0,
    100.0
  );
}

// ================ STABLE LED CONTROL ================

void updateLED() {

  if (!monitoringUnlocked) {

    currentLEDState = LED_OFF;
    setRGB(0, 0, 0);

    return;
  }

  // Turn LED off when the container is empty.
  // A small threshold prevents flickering near zero.

  if (waterPercentage <= 0.3) {

    currentLEDState = LED_OFF;

  } else {

    switch (currentLEDState) {

      // ---------------------------------
      // LED OFF
      // ---------------------------------

      case LED_OFF:

        if (waterPercentage >= 1.0) {

          if (waterPercentage >= 77.0) {
            currentLEDState = LED_RED;
          }

          else if (waterPercentage >= 61.0) {
            currentLEDState = LED_YELLOW;
          }

          else {
            currentLEDState = LED_GREEN;
          }
        }

        break;

      // ---------------------------------
      // GREEN
      // ---------------------------------

      case LED_GREEN:

        if (waterPercentage >= 77.0) {

          currentLEDState = LED_RED;

        }

        else if (waterPercentage >= 61.0) {

          currentLEDState = LED_YELLOW;

        }

        break;

      // ---------------------------------
      // YELLOW
      // ---------------------------------

      case LED_YELLOW:

        if (waterPercentage >= 77.0) {

          currentLEDState = LED_RED;

        }

        else if (waterPercentage <= 59.0) {

          currentLEDState = LED_GREEN;

        }

        break;

      // ---------------------------------
      // RED
      // ---------------------------------

      case LED_RED:

        if (waterPercentage <= 59.0) {

          currentLEDState = LED_GREEN;

        }

        else if (waterPercentage <= 74.0) {

          currentLEDState = LED_YELLOW;

        }

        break;
    }
  }

  // Apply the selected LED color.

  switch (currentLEDState) {

    case LED_OFF:

      setRGB(0, 0, 0);

      break;

    case LED_GREEN:

      setRGB(0, 255, 0);

      break;

    case LED_YELLOW:

      setRGB(255, 180, 0);

      break;

    case LED_RED:

      setRGB(255, 0, 0);

      break;
  }
}

// ================ BUZZER ================

void updateBuzzer() {

  unsigned long now = millis();

  if (!monitoringUnlocked || waterPercentage <= 0) {

    digitalWrite(BUZZER_PIN, LOW);

    buzzerState = false;

    return;
  }

  // Continuous warning at 99.5% and above.

  if (waterPercentage >= 99.5) {

    digitalWrite(BUZZER_PIN, HIGH);

    buzzerState = true;

    return;
  }

  unsigned long interval = 0;

  // Fast warning.

  if (waterPercentage >= 95) {

    interval = 150;

  }

  // Slow warning.

  else if (waterPercentage >= 80) {

    interval = 600;

  }

  // No warning below 80%.

  if (interval == 0) {

    digitalWrite(BUZZER_PIN, LOW);

    buzzerState = false;

    return;
  }

  if (now - lastBeepChange >= interval) {

    lastBeepChange = now;

    buzzerState = !buzzerState;

    digitalWrite(
      BUZZER_PIN,
      buzzerState ? HIGH : LOW
    );
  }
}

// ================ OUTPUT CONTROL ================

void updateOutputs() {

  if (!monitoringUnlocked) {

    turnOffOutputs();

    return;
  }

  updateLED();

  updateBuzzer();
}

// ================ SERIAL COMMANDS ================

void processCommand(String command) {

  command.trim();

  // ---------------------------------
  // LOCK COMMAND
  // ---------------------------------

  if (command == "LOCK") {

    monitoringUnlocked = false;

    turnOffOutputs();

    return;
  }

  // ---------------------------------
  // STATUS COMMAND
  // ---------------------------------

  if (command.startsWith("STATUS,")) {

    int firstComma = command.indexOf(',');

    int secondComma = command.indexOf(
      ',',
      firstComma + 1
    );

    if (secondComma > 0) {

      String percentText = command.substring(
        firstComma + 1,
        secondComma
      );

      String tempText = command.substring(
        secondComma + 1
      );

      float incomingPercentage = percentText.toFloat();

      updateFilteredPercentage(incomingPercentage);

      float receivedTemp = tempText.toFloat();

      if (receivedTemp > -50 && receivedTemp < 100) {

        temperature = receivedTemp;
      }

      monitoringUnlocked = true;

      lastDashboardMessage = millis();
    }
  }
}

// ================ SERIAL INPUT ================

void readSerialCommands() {

  while (Serial.available() > 0) {

    char incoming = Serial.read();

    if (incoming == '\n') {

      processCommand(inputCommand);

      inputCommand = "";
    }

    else if (incoming != '\r') {

      if (inputCommand.length() < 100) {

        inputCommand += incoming;

      } else {

        inputCommand = "";
      }
    }
  }
}

// ================ SETUP ================

void setup() {

  Serial.begin(9600);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  pinMode(RED_PIN, OUTPUT);
  pinMode(GREEN_PIN, OUTPUT);
  pinMode(BLUE_PIN, OUTPUT);

  pinMode(BUZZER_PIN, OUTPUT);

  dht.begin();

  turnOffOutputs();
}

// ================ MAIN LOOP ================

void loop() {

  unsigned long now = millis();

  // Read commands from dashboard.

  readSerialCommands();

  // Dashboard connection watchdog.

  if (
    monitoringUnlocked &&
    now - lastDashboardMessage > DASHBOARD_TIMEOUT
  ) {

    monitoringUnlocked = false;

    turnOffOutputs();
  }

  // Read ultrasonic sensor.

  if (now - lastSensorRead >= SENSOR_INTERVAL) {

    lastSensorRead = now;

    distanceCM = readFilteredDistance();
  }

  // Read DHT11.

  if (now - lastDHTRead >= DHT_INTERVAL) {

    lastDHTRead = now;

    float newTemp = dht.readTemperature();

    float newHumidity = dht.readHumidity();

    if (!isnan(newTemp)) {
      temperature = newTemp;
    }

    if (!isnan(newHumidity)) {
      humidity = newHumidity;
    }
  }

  // Send sensor readings to dashboard.

  static unsigned long lastSerialSend = 0;

  if (now - lastSerialSend >= 500) {

    lastSerialSend = now;

    Serial.print("DATA,");

    Serial.print(distanceCM, 2);

    Serial.print(",");

    Serial.print(temperature, 1);

    Serial.print(",");

    Serial.println(humidity, 1);
  }

  // Update LEDs and buzzer.

  updateOutputs();
}
