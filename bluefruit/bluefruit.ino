#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Adafruit_TinyUSB.h>
#include <bluefruit.h>

Adafruit_NeoPixel pixels(10, 8, NEO_GRB + NEO_KHZ800);

void scan_callback(ble_gap_evt_adv_report_t*);

void setup() {
  Serial.begin(115200);

  Bluefruit.begin(0, 5);    // peripheral, central connections
  Bluefruit.setTxPower(8);  // +8dB (supported by nRF52840)
  Bluefruit.setName("NametagManager");
  Bluefruit.Scanner.setRxCallback(scan_callback);
  Bluefruit.Scanner.restartOnDisconnect(true);
  Bluefruit.Scanner.setInterval(160, 80);  // interval, window (x0.625ms)
  Bluefruit.Scanner.useActiveScan(true);
  // Bluefruit.Scanner.filterUuid(BLEUuid(0xFFF1));
  Bluefruit.Scanner.start(0);
  Serial.println("Scanning...");
}

void loop() {
  Serial.println("Running...");
  delay(1000);
}

void scan_callback(ble_gap_evt_adv_report_t* report)
{
  uint8_t name[32] = {};
  Bluefruit.Scanner.parseReportByType(
      report, BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME, name, sizeof(name));
  if (memcmp(name, "CoolLED", 7)) {
    Bluefruit.Scanner.resume();
    return;
  }

  Serial.printBufferReverse(report->peer_addr.addr, 6, ':');
  Serial.printf(" %s", report->type.scan_response ? "SR" : "AD");
  Serial.printf(" %+3ddBm", report->rssi);
  Serial.printf(" %c", report->type.connectable ? 'C' : 'n');
  Serial.printf("/%c", report->type.directed ? 'D' : 'u');
  if (name[0]) Serial.printf(" [%s]", name);
  Serial.println();
  Bluefruit.Scanner.resume();
}

void printUuid16List(uint8_t* buffer, uint8_t len)
{
  Serial.printf("%14s %s", "16-Bit UUID");
  for(int i=0; i<len; i+=2)
  {
    uint16_t uuid16;
    memcpy(&uuid16, buffer+i, 2);
    Serial.printf("%04X ", uuid16);
  }
  Serial.println();
}

void printUuid128List(uint8_t* buffer, uint8_t len)
{
  (void) len;
  Serial.printf("%14s %s", "128-Bit UUID");

  // Print reversed order
  for(int i=0; i<16; i++)
  {
    const char* fm = (i==4 || i==6 || i==8 || i==10) ? "-%02X" : "%02X";
    Serial.printf(fm, buffer[15-i]);
  }

  Serial.println();  
}
