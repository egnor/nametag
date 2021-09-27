#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Adafruit_TinyUSB.h>

#include <ble.h>
#include <nrfx_power.h>

// Adafruit_NeoPixel pixels(10, 8, NEO_GRB + NEO_KHZ800);

static void bluetooth_setup();
static void bluetooth_poll();
static void on_bt_scan_report(uint16_t, const ble_gap_evt_adv_report_t *);
static void on_bt_connect(uint16_t, const ble_gap_evt_connected_t *);
static void on_bt_disconn(uint16_t, const ble_gap_evt_disconnected_t *);
static void on_bt_update_request(
    uint16_t h, const ble_gap_evt_conn_param_update_request_t *request);
static void on_bt_timeout(const ble_gap_evt_timeout_t *);
static void on_bt_read_reply(const ble_gattc_evt_t *);
static void on_bt_write_done(const ble_gattc_evt_t *);
static void on_bt_fault(uint32_t, uint32_t, uint32_t);
extern "C" void tusb_hal_nrf_power_event(uint32_t);

static void input_poll();
static void on_input_line();
static void on_conn_command(const String &);
static void on_disconn_command(const String &);
static void on_read_command(const String &);
static void on_write_command(const String &);

static void print_address(const ble_gap_addr_t *);
static void print_escaped(const uint8_t *, int);

static uint8_t scan_data[BLE_GAP_SCAN_BUFFER_MAX];
static const ble_data_t scan_data_info = {scan_data, sizeof(scan_data)};
static bool show_scan = true;
static int conn_pending = 0;

String input_line;
static enum { INPUT_TEXT, INPUT_HEX1, INPUT_HEX2 } input_state = INPUT_TEXT;
static uint32_t next_status_millis = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(1);
  bluetooth_setup();
  input_line.reserve(256);
}

void loop() {
  const auto now = millis();
  if (now >= next_status_millis) {
    next_status_millis = now + 1000;
    Serial.printf("--- time=%d\n", now / 1000);
    digitalToggle(LED_BUILTIN);
  }
  bluetooth_poll();
  input_poll();
}

static void bluetooth_setup() {
  // Disable TinyUSB peripheral event handlers (needed by SD).
  nrfx_power_usbevt_disable();
  nrfx_power_usbevt_uninit();
  nrfx_power_uninit();

  // Default RC clock is good for the Circuit Playground Bluefruit.
  sd_softdevice_enable(nullptr, on_bt_fault);

  // Enable TinyUSB *soft device* event handlers passed through.
  sd_power_usbdetected_enable(true);
  sd_power_usbpwrrdy_enable(true);
  sd_power_usbremoved_enable(true);

  // Handle lost USB READY event during setup (as in bluefruit.cpp).
  uint32_t usb_reg;
  sd_power_usbregstatus_get(&usb_reg);
  if ((usb_reg & POWER_USBREGSTATUS_OUTPUTRDY_Msk) && !NRF_USBD->USBPULLUP) {
    tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_READY);
  }

  extern const uint32_t __data_start__[];  // Start of app RAM
  const uint32_t app_ram_base = (uint32_t) __data_start__;
  static const ble_cfg_t role_config = {
    .gap_cfg = {
      .role_count_cfg = {
        .periph_role_count = 0,
        .central_role_count = 10,
        .central_sec_count = 1
      }
    }
  };
  const auto role_error = sd_ble_cfg_set(
      BLE_GAP_CFG_ROLE_COUNT, &role_config, app_ram_base
  );
  if (role_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=BLE_GAP_CFG_ROLE_COUNT code=0x%x\n", role_error);
  }

  uint32_t app_ram_needed = app_ram_base;
  const auto enable_error = sd_ble_enable(&app_ram_needed);
  if (enable_error == NRF_ERROR_NO_MEM) {
    Serial.printf(
        "*** ERR=sd_ble_enable code=NO_MEM alloc=0x%x, needed=0x%x\n",
        app_ram_base, app_ram_needed
    );
    return;
  } else if (enable_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_enable code=0x%x\n", enable_error);
    return;
  }

  const auto power_error = sd_ble_gap_tx_power_set(
      BLE_GAP_TX_POWER_ROLE_SCAN_INIT, 0, +8
  );
  if (power_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_gap_tx_power_set code=0x%x\n", power_error);
  }
}

static void bluetooth_poll() {
  while (true) {
    uint32_t sd_event_id;
    const auto event_error = sd_evt_get(&sd_event_id);
    if (event_error == NRF_ERROR_NOT_FOUND) {
      break;
    } else if (event_error != NRF_SUCCESS) {
      Serial.printf("*** ERR=sd_evt_get code=0x%x\n", event_error);
      break;
    }

    switch (sd_event_id) {
      case NRF_EVT_POWER_USB_DETECTED:
        tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_DETECTED);
        break;
      case NRF_EVT_POWER_USB_POWER_READY:
        tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_READY);
        break;
      case NRF_EVT_POWER_USB_REMOVED:
        tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_REMOVED);
        break;
    }
  }

  constexpr int max_event_size = BLE_EVT_LEN_MAX(BLE_GATT_ATT_MTU_DEFAULT);
  uint8_t event_buffer[max_event_size];
  while (true) {
    uint16_t event_size = max_event_size;
    const auto event_error = sd_ble_evt_get(event_buffer, &event_size);
    if (event_error == NRF_ERROR_NOT_FOUND) {
      break;
    } else if (event_error == NRF_ERROR_DATA_SIZE) {
      Serial.printf(
          "*** ERR=sd_ble_evt_get code=DATA_SIZE alloc=0x%x, needed=0x%x\n",
          max_event_size, event_size
      );
      break;
    } else if (event_error != NRF_SUCCESS) {
      Serial.printf("*** ERR=sd_ble_evt_get code=0x%x\n", event_error);
      break;
    }

    const ble_evt_t *event = (const ble_evt_t *) event_buffer;
    const auto handle = event->evt.common_evt.conn_handle;
    switch (event->header.evt_id) {
      case BLE_GAP_EVT_ADV_REPORT:
        on_bt_scan_report(&event->evt.gap_evt.params.adv_report);
        break;
      case BLE_GAP_EVT_CONNECTED:
        on_bt_connect(handle, &event->evt.gap_evt.params.connected);
        break;
      case BLE_GAP_EVT_DISCONNECTED:
        on_bt_disconn(handle, &event->evt.gap_evt.params.disconnected);
        break;
      case BLE_GAP_EVT_CONN_PARAM_UPDATE_REQUEST:
        on_bt_update_request(
            handle, &event->evt.gap_evt.params.conn_param_update_request
        );
        break;
      case BLE_GAP_EVT_TIMEOUT:
        on_bt_timeout(handle, &event->evt.gap_evt.params.timeout);
        break;
      case BLE_GATTC_EVT_READ_RSP:
        on_bt_read_reply(&event->evt.gattc_evt);
        break;
      case BLE_GATTC_EVT_WRITE_CMD_TX_COMPLETE:
        on_bt_write_done(&event->evt.gattc_evt);
        break;
      default:
        Serial.printf("ble_event=%d handle=%d\n", event->header.evt_id, handle);
        break;
    }
  }

  if (conn_pending == 0) {
    static const ble_gap_scan_params_t scan_params = {
      .active = 0,
      .interval = 23,
      .window = 13,
    };

    const auto error = sd_ble_gap_scan_start(&scan_params, &scan_data_info);
    if (error == NRF_SUCCESS) {
      Serial.println("scan_start");
    } else if (error != NRF_ERROR_INVALID_STATE) {
      Serial.printf("*** ERR=sd_ble_gap_scan_start code=0x%x\n", error);
    }
  }
}

static void on_bt_scan_report(const ble_gap_evt_adv_report_t *report) {
  if (show_scan && Serial) {
    uint8_t flags = 0;
    const char *name_data = nullptr, *name_end = nullptr;
    const uint8_t *uuid16_data = nullptr, *uuid16_end = nullptr;
    const uint8_t *specific_data = nullptr, *specific_end = nullptr;
    uint8_t others[10], num_others = 0;

    const uint8_t *data = report->data.p_data;
    const uint8_t *end = data + report->data.len;
    while (data < end && &data[1] + data[0] <= end) {
      const uint8_t ad_type = data[1];
      const uint8_t *ad_data = &data[2];
      const uint8_t *ad_end = &data[1] + data[0];
      switch (data[1]) {
        case BLE_GAP_AD_TYPE_FLAGS:
          flags = (ad_end > ad_data) ? ad_data[0] : 0;
          break;
        case BLE_GAP_AD_TYPE_SHORT_LOCAL_NAME:
        case BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME:
          name_data = (const char *) ad_data;
          name_end = (const char *) ad_end;
          break;
        case BLE_GAP_AD_TYPE_16BIT_SERVICE_UUID_MORE_AVAILABLE:
        case BLE_GAP_AD_TYPE_16BIT_SERVICE_UUID_COMPLETE:
          uuid16_data = ad_data;
          uuid16_end = ad_end;
          break;
        case BLE_GAP_AD_TYPE_MANUFACTURER_SPECIFIC_DATA:
          specific_data = ad_data;
          specific_end = ad_end;
          break;
        default:
          if (num_others < sizeof(others)) {
            others[num_others++] = data[1];
          }
          break;
      }

      data = ad_end;
    }

    Serial.print("scan=");
    print_address(&report->peer_addr);

    Serial.printf(
        " t=%s:%c%c%c%c",
        report->type.scan_response ? "SR" : "AD",
        report->type.connectable ? 'C' : 'c',
        report->type.scannable ? 'S' : 's',
        report->type.directed ? 'D' : 'd',
        report->type.extended_pdu ? 'X' : 'x'
    );
    if (flags) {
      Serial.printf(
          " f=%c%c",
          (flags & BLE_GAP_ADV_FLAG_LE_LIMITED_DISC_MODE) ? 'l' :
          (flags & BLE_GAP_ADV_FLAG_LE_GENERAL_DISC_MODE) ? 'G' : '.',
          (flags & BLE_GAP_ADV_FLAG_BR_EDR_NOT_SUPPORTED) ? '/' :
          (flags & BLE_GAP_ADV_FLAG_LE_BR_EDR_CONTROLLER) ? 'C' :
          (flags & BLE_GAP_ADV_FLAG_LE_BR_EDR_HOST) ? 'H' : '?'
      );
    }
    Serial.printf(" s=%-+3d", report->rssi);
    if (uuid16_data) {
      Serial.print(" u=");
      for (const uint8_t *u = uuid16_data; u + 2 <= uuid16_end; u += 2) {
        Serial.printf("%s%02x%02x", u != uuid16_data ? "," : "", u[1], u[0]);
      }
    }
    if (name_data) {
      Serial.printf(" n=\"%.*s\"", name_end - name_data, name_data);
    }
    if (specific_data) {
      Serial.print(" m=");
      print_escaped(specific_data, specific_end - specific_data);
    }
    for (int i = 0; i < num_others; ++i) {
      Serial.printf(" ad=0x%02x", others[i]);
    }
    Serial.print("\n");
  }

  const auto scan_error = sd_ble_gap_scan_start(nullptr, &scan_data_info);
  if (scan_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_gap_scan_start code=0x%x\n", scan_error);
  }
}

static void on_bt_connect(uint16_t h, const ble_gap_evt_connected_t *conn) {
  Serial.printf("conn=");
  print_address(&conn->peer_addr);
  Serial.printf(" handle=%d pending=%d\n", h, --conn_pending);
}

static void on_bt_disconn(uint16_t h, const ble_gap_evt_disconnected_t *dc) {
  Serial.printf("disconn handle=%d reason=0x%02x\n", h, dc->reason);
}

static void on_bt_update_request(
    uint16_t h, const ble_gap_evt_conn_param_update_request_t *request) {
  const auto *params = &request->conn_params;
  Serial.printf(
      "update_req handle=%d min_conn=%d max_conn=%d latency=%d conn_sup=%d\n",
      h, params->min_conn_interval, params->max_conn_interval,
      params->slave_latency, params->conn_sup_timeout
  );
}

static void on_bt_timeout(uint16_t h, const ble_gap_evt_timeout_t *timeout) {
  switch (timeout->src) {
    case BLE_GAP_TIMEOUT_SRC_SCAN:
      Serial.printf("scan_timeout\n");
      break;
    case BLE_GAP_TIMEOUT_SRC_CONN:
      Serial.printf("conn_timeout pending=%d\n", --conn_pending);
      break;
    case BLE_GAP_TIMEOUT_SRC_AUTH_PAYLOAD:
      Serial.printf("auth_timeout handle=%d\n", h);
      break;
    default:
      Serial.printf("timeout src=%d\n", timeout->src);
      break;
  }
}

static void on_bt_read_reply(const ble_gattc_evt_t *e) {
  if (e->gatt_status == BLE_GATT_STATUS_SUCCESS) {
    const auto *rr = &e->params.read_rsp;
    Serial.printf("read handle=%d attr=%d data=", e->conn_handle, rr->handle);
    print_escaped(rr->data, rr->len);
    Serial.println();
  } else {
    Serial.printf(
        "read handle=%d attr=%d error=0x%x\n",
        e->conn_handle, e->error_handle, e->gatt_status
    );
  }
}

static void on_bt_write_done(const ble_gattc_evt_t *e) {
  if (e->gatt_status == BLE_GATT_STATUS_SUCCESS) {
    const auto *wr = &e->params.write_cmd_tx_complete;
    Serial.printf("write handle=%d done=%d\n", e->conn_handle, wr->count);
  } else {
    Serial.printf(
        "write handle=%d attr=%d error=0x%x\n",
        e->conn_handle, e->error_handle, e->gatt_status
    );
  }
}

static void on_bt_fault(uint32_t id, uint32_t pc, uint32_t info) {
  switch (id) {
    case NRF_FAULT_ID_APP_MEMACC:
      Serial.printf("*** ERR=APP_MEMACC PC=0x%08x info=%d\n", pc, info);
      break;
    case NRF_FAULT_ID_SD_ASSERT:
      struct SourceLoc { uint16_t line; const char *file; };
      Serial.printf(
          "*** ERR=SD_ASSERT PC=0x%08x file=\"%s\" line=%d\n",
          pc, ((SourceLoc *) info)->line, ((SourceLoc *) info)->file
      );
      break;
    default:
      Serial.printf("*** ERR=ble_fault code=0x%x PC=0x%08x\n", id, pc);
      break;
  }

  // 1/sec quick flash for NRF fault.
  while (true) {
    digitalWrite(LED_BUILTIN, true);
    delay(50);
    digitalWrite(LED_BUILTIN, false);
    delay(950);
  }
}

static void input_poll() {
  while (Serial.available()) {
    const char ch = Serial.read(); 
    if (ch == '\r' or ch == '\n') {
      input_line.trim();
      if (input_line.length()) on_input_line();
      input_line.remove(0);
    } else if (ch < 32 || ch >= 128) {
      Serial.printf("*** ERR=bad_input ascii=%d\n", ch);
    } else if (input_line.length() >= 255) {
      Serial.printf("*** ERR=bad_input length=%d\n", input_line.length());
      input_line.remove(0);
    } else {
      input_line += ch;
    }
  }
}

static void on_input_line() {
  if (input_line.startsWith("echo ")) {
    String copy = input_line.substring(5);
    copy.trim();
    decode_escaped(&copy);
    Serial.print("echo line=");
    print_escaped((uint8_t *) copy.c_str(), copy.length());
    Serial.println();
  } else if (input_line.startsWith("conn ")) {
    on_conn_command(input_line.substring(5));
  } else if (input_line.startsWith("disconn ")) {
    on_disconn_command(input_line.substring(8));
  } else if (input_line.startsWith("read ")) {
    on_read_command(input_line.substring(5));
  } else if (input_line.startsWith("write ")) {
    on_write_command(input_line.substring(6));
  } else if (input_line == "mute") {
    show_scan = false;
    Serial.println("scan_show=false");
  } else if (input_line == "show") {
    show_scan = true;
    Serial.println("scan_show=true");
  } else {
    Serial.printf("*** ERR=bad_input command=\"%s\"\n", input_line.c_str());
  }
}

static void on_conn_command(const String &args) {
  ble_gap_addr_t addr = {};
  int byte_index = 5;
  const char *pch = args.c_str();
  while (*pch) {
    char *end;
    const int b = strtoul(pch, &end, 16);
    if (end > pch) {
      if (b < 0 || b > 0xff || byte_index < 0) {
        Serial.printf("*** ERR=bad_input conn_addr=\"%s\"\n", pch);
        return;
      } else {
        addr.addr[byte_index--] = b;
        pch = end;
      }
    } else if (*pch == ':' || *pch == '/' || *pch == ' ') {
      ++pch;
    } else if (!strncmp(pch, "pub", 3)) {
      addr.addr_type = BLE_GAP_ADDR_TYPE_PUBLIC;
      pch += 3;
    } else if (!strncmp(pch, "rst", 3)) {
      addr.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_STATIC;
      pch += 3;
    } else if (!strncmp(pch, "rpr", 3)) {
      addr.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_RESOLVABLE;
      pch += 3;
    } else if (!strncmp(pch, "rpn", 3)) {
      addr.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_NON_RESOLVABLE;
      pch += 3;
    } else {
      Serial.printf("*** ERR=bad_input conn_addr=\"%s\"\n", pch);
      return;
    }
  }
  if (byte_index >= 0) {
    Serial.printf("*** ERR=bad_input conn=\"%s\"\n", args.c_str());
    return;
  }

  static const ble_gap_scan_params_t conn_scan_params = {
    .interval = 37,
    .window = 31,
    .timeout = 300,  // *10ms = 3 sec
  };

  static const ble_gap_conn_params_t connect_params = {
    .min_conn_interval = 13,
    .max_conn_interval = 13,  // *1.25ms
    .slave_latency = 4,
    .conn_sup_timeout = 300,  // *10ms = 3 sec
  };

  const auto connect_error = sd_ble_gap_connect(
      &addr, &conn_scan_params, &connect_params, BLE_CONN_CFG_TAG_DEFAULT
  );
  if (connect_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_gap_connect code=0x%x\n", connect_error);
    return;
  }
  Serial.print("conn_start=");
  print_address(&addr);
  Serial.printf(" pending=%d\n", ++conn_pending);
}

static void on_disconn_command(const String &args) {
  char *end;
  const int handle = strtoul(args.c_str(), &end, 10);
  if (*end) {
    Serial.printf("*** ERR=bad_input disconn=\"%s\"\n", args.c_str());
    return;
  }
  const auto disconn_error = sd_ble_gap_disconnect(
      handle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION
  );
  if (disconn_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_gap_disconnect code=0x%x\n", disconn_error);
    return;
  }
  Serial.printf("disconn_start=%d\n", handle);
}

static void on_read_command(const String &args) {
  const char *arg = args.c_str();
  char *end;
  const int conn = strtoul(arg, &end, 10);
  if (end == arg) {
    Serial.printf("*** ERR=bad_input read=\"%s\"\n", arg);
    return;
  }

  for (arg = end; *arg == ' '; ++arg) {}
  const int attr = strtoul(arg, &end, 10);
  if (end == arg || *end) {
    Serial.printf("*** ERR=bad_input read=\"%s\"\n", arg);
    return;
  }

  const auto read_error = sd_ble_gattc_read(conn, attr, 0);
  if (read_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_gattc_read code=0x%x\n", read_error);
    if (read_error == NRF_ERROR_TIMEOUT) {
      sd_ble_gap_disconnect(conn, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    }
    return;
  }
  Serial.printf("read_start handle=%d attr=%d\n", conn, attr);
}

static void on_write_command(const String &args) {
  const char *arg = args.c_str();
  char *end;
  const int conn = strtoul(arg, &end, 10);
  if (end == arg) {
    Serial.printf("*** ERR=bad_input write=\"%s\"\n", arg);
    return;
  }

  for (arg = end; *arg == ' '; ++arg) {}
  const int attr = strtoul(arg, &end, 10);
  if (end == arg) {
    Serial.printf("*** ERR=bad_input write=\"%s\"\n", arg);
    return;
  }

  for (arg = end; *arg == ' '; ++arg) {}
  String data(arg);
  decode_escaped(&data);

  const ble_gattc_write_params_t write_params = {
    .write_op = BLE_GATT_OP_WRITE_CMD,
    .handle = attr,
    .len = data.length(),
    .p_value = (const uint8_t *) data.c_str(),
  };
  const auto write_error = sd_ble_gattc_write(conn, &write_params);
  if (write_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_gattc_write code=0x%x\n", write_error);
    if (write_error == NRF_ERROR_TIMEOUT) {
      sd_ble_gap_disconnect(conn, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    }
    return;
  }
  Serial.printf("write_start handle=%d attr=%d\n", conn, attr);
}

static void print_address(const ble_gap_addr_t *addr) {
  if (addr->addr_type == BLE_GAP_ADDR_TYPE_ANONYMOUS) {
    Serial.print("anon");
  } else {
    const auto &a = addr->addr;
    Serial.printf(
        "%02x:%02x:%02x:%02x:%02x:%02x", a[5], a[4], a[3], a[2], a[1], a[0]
    );
    switch (addr->addr_type) {
      case BLE_GAP_ADDR_TYPE_PUBLIC:
        Serial.print("/pub");
        break;
      case BLE_GAP_ADDR_TYPE_RANDOM_STATIC:
        Serial.print("/rst");
        break;
      case BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_RESOLVABLE:
        Serial.print("/rpr");
        break;
      case BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_NON_RESOLVABLE:
        Serial.print("/rpn");
        break;
      default:
        Serial.printf("/t%d", addr->addr_type);
        break;
    }
  }
}

static void decode_escaped(String *str) {
  int index = 0;
  while (index < str->length()) {
    const char ch = str->charAt(index);
    if (ch == '"') {
      str->remove(index, 1);
    } else if (ch == '^') {
      char *end;
      const auto hex = str->substring(index + 1, index + 3);
      str->setCharAt(index, strtoul(hex.c_str(), &end, 16));
      str->remove(index + 1, 2);
      if (*end) {
        Serial.printf("*** ERR=bad_input escape=\"%s\"\n", hex.c_str());
      }
    } else {
      ++index;
    }
  }
}

static void print_escaped(const uint8_t *bytes, int size) {
  Serial.print("\"");
  for (int i = 0; i < size; ++i) {
    const auto b = bytes[i];
    if (b >= 32 && b < 128 && b != '^' && b != '"') {
      Serial.write(b);
    } else {
      Serial.printf("^%02x", b);
    }
  }
  Serial.print("\"");
}
