#include <Adafruit_TinyUSB.h>

#include <Arduino.h>
#include <Adafruit_TinyUSB.h>

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    digitalWrite(LED_BUILTIN, (millis() % 500) < 50);
    delay(10);
  }
}

void loop() {
  if (Serial.available()) {
    const char ch = Serial.read();
    Serial.write(ch);
    digitalToggle(LED_BUILTIN);
  }
}
