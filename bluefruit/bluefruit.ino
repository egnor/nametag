#include <ctype.h>
#include <stdio.h>

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Adafruit_TinyUSB.h>

#include <ble.h>
#include <nrfx_power.h>

// Adafruit_NeoPixel pixels(10, 8, NEO_GRB + NEO_KHZ800);

static void input_poll();
static void on_input_line(char *);
static void on_conn_command(char *);
static void on_disconn_command(char *);
static void on_read_command(char *);
static void on_write_command(char *);

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

static char *split_word(char **);
static int decode_escaped(char *);
static void print_escaped(const void *, int);
static void print_address(const ble_gap_addr_t *);

static uint8_t scan_data[BLE_GAP_SCAN_BUFFER_MAX];
static const ble_data_t scan_data_info = {scan_data, sizeof(scan_data)};
static bool show_scan = true;

char input_line[256];
int input_size = 0;
static uint32_t next_status_millis = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);
  bluetooth_setup();
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

static void input_poll() {
  while (Serial.available()) {
    const char ch = Serial.read(); 
    if (ch == '\r' or ch == '\n') {
      input_line[input_size] = '\0';
      on_input_line(input_line);
      input_size = 0;
    } else if (ch < 32 || ch >= 128) {
      Serial.printf("*** ERR=input ascii=%d\n", ch);
    } else if (input_size >= sizeof(input_line) - 1) {
      Serial.printf("*** ERR=input line_length=%d\n", input_size);
      input_size = 0;
    } else {
      input_line[input_size++] = ch;
    }
  }

  if (!Serial) {
    for (int h = 0; h < 20; ++h) {
      sd_ble_gap_disconnect(h, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    }
  }
}

static void on_input_line(char *line) {
  const char *command = split_word(&line);
  if (!strcmp(command, "echo")) {
    const int size = decode_escaped(line);
    Serial.print("echo=");
    print_escaped(line, size);
    Serial.println();
  } else if (!strcmp(command, "conn")) {
    on_conn_command(line);
  } else if (!strcmp(command, "disconn")) {
    on_disconn_command(line);
  } else if (!strcmp(command, "read")) {
    on_read_command(line);
  } else if (!strcmp(command, "write")) {
    on_write_command(line);
  } else if (!strcmp(command, "hide")) {
    show_scan = false;
    Serial.println("show=false");
  } else if (!strcmp(command, "show")) {
    show_scan = true;
    Serial.println("show=true");
  } else if (*command) {
    Serial.printf("*** ERR=input command=\"%s\"", command);
    Serial.println();
  }
}

static void on_conn_command(char *args) {
  int ab[6];
  char *addr_text = split_word(&args), type_text[4];
  const int parsed = sscanf(
      addr_text, "%2x:%2x:%2x:%2x:%2x:%2x/%3s",
      &ab[5], &ab[4], &ab[3], &ab[2], &ab[1], &ab[0], type_text);
  if (parsed != 7) {
    Serial.printf("*** ERR=input in=conn addr=\"%s\"\n", addr_text);
    return;
  }

  ble_gap_addr_t addr = {};
  for (int i = 0; i < 6; ++i) addr.addr[i] = ab[i];

  if (!strcmp(type_text, "pub")) {
    addr.addr_type = BLE_GAP_ADDR_TYPE_PUBLIC;
  } else if (!strcmp(type_text, "rst")) {
    addr.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_STATIC;
  } else if (!strcmp(type_text, "rpr")) {
    addr.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_RESOLVABLE;
  } else if (!strcmp(type_text, "rpn")) {
    addr.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_NON_RESOLVABLE;
  } else {
    Serial.printf("*** ERR=input in=conn addr=\"%s\"\n", addr_text);
    return;
  }

  if (*args) {
    Serial.printf("*** ERR=input in=conn extra=\"%s\"\n", split_word(&args));
    return;
  }

  static const ble_gap_scan_params_t conn_scan_params = {
    .interval = 23,
    .window = 13,
    .timeout = 300,  // *10ms = 3 sec
  };

  static const ble_gap_conn_params_t connect_params = {
    .min_conn_interval = 13,
    .max_conn_interval = 13,  // *1.25ms
    .slave_latency = 4,
    .conn_sup_timeout = 300,  // *10ms = 3 sec
  };

  const auto connect_error = sd_ble_gap_connect(
      &addr, &conn_scan_params, &connect_params, BLE_CONN_CFG_TAG_DEFAULT);
  if (connect_error != NRF_SUCCESS) {
    Serial.print("*** conn_fail=");
    print_address(&addr);
    Serial.printf(" code=0x%x\n", connect_error);
    return;
  }
  Serial.print("conn_start=");
  print_address(&addr);
  Serial.println();
}

static void on_disconn_command(char *args) {
  char *end, *handle_text = split_word(&args);
  const int handle = strtol(handle_text, &end, 10);
  if (!*handle_text || *end) {
    Serial.printf("*** ERR=input in=disconn handle=\"%s\"\n", handle_text);
    return;
  }

  if (*args) {
    Serial.printf("*** ERR=input in=disconn extra=\"%s\"\n", split_word(&args));
    return;
  }

  const auto disconn_error = sd_ble_gap_disconnect(
      handle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
  if (disconn_error != NRF_SUCCESS) {
    Serial.printf(
        "*** disconn_fail conn=%d code=0x%x\n", handle, disconn_error);
    return;
  }
  Serial.printf("disconn_start conn=%d\n", handle);
}

static void on_read_command(char *args) {
  char *end, *conn_text = split_word(&args);
  const int conn_handle = strtoul(conn_text, &end, 10);
  if (!*conn_text || *end) {
    Serial.printf("*** ERR=input in=read handle=\"%s\"\n", conn_text);
    return;
  }

  char *attr_text = split_word(&args);
  const int attr_handle = strtoul(attr_text, &end, 10);
  if (!*attr_text || *end) {
    Serial.printf("*** ERR=input in=read handle=\"%s\"\n", attr_text);
    return;
  }

  if (*args) {
    Serial.printf("*** ERR=input in=read extra=\"%s\"\n", split_word(&args));
    return;
  }

  const auto read_error = sd_ble_gattc_read(conn_handle, attr_handle, 0);
  if (read_error != NRF_SUCCESS) {
    Serial.printf(
        "*** read_fail conn=%d attr=%d code=0x%x\n",
        conn_handle, attr_handle, read_error);
    if (read_error == NRF_ERROR_TIMEOUT) {
      sd_ble_gap_disconnect(
          conn_handle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    }
    return;
  }
  Serial.printf("read_start conn=%d attr=%d\n", conn_handle, attr_handle);
}

static void on_write_command(char *args) {
  char *end, *conn_text = split_word(&args);
  const int conn_handle = strtoul(conn_text, &end, 10);
  if (!*conn_text || *end) {
    Serial.printf("*** ERR=input in=write handle=\"%s\"\n", conn_text);
    return;
  }

  char *attr_text = split_word(&args);
  const int attr_handle = strtoul(attr_text, &end, 10);
  if (!*attr_text || *end) {
    Serial.printf("*** ERR=input in=write handle=\"%s\"\n", attr_text);
    return;
  }

  char *data = split_word(&args);
  const int data_size = decode_escaped(data);
  if (*args) {
    Serial.printf("*** ERR=input in=write extra=\"%s\"\n", split_word(&args));
    return;
  }

  const ble_gattc_write_params_t write_params = {
    .write_op = BLE_GATT_OP_WRITE_CMD,
    .handle = attr_handle,
    .len = data_size,
    .p_value = (const uint8_t *) data,
  };
  const auto write_error = sd_ble_gattc_write(conn_handle, &write_params);
  if (write_error != NRF_SUCCESS) {
    Serial.printf(
        "*** write_fail conn=%d attr=%d code=0x%x\n",
        conn_handle, attr_handle, write_error);
    if (write_error == NRF_ERROR_TIMEOUT) {
      sd_ble_gap_disconnect(
          conn_handle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    }
    return;
  }
  Serial.printf("write_start conn=%d attr=%d\n", conn_handle, attr_handle);
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
      BLE_GAP_CFG_ROLE_COUNT, &role_config, app_ram_base);
  if (role_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=BLE_GAP_CFG_ROLE_COUNT code=0x%x\n", role_error);
  }

  uint32_t app_ram_needed = app_ram_base;
  const auto enable_error = sd_ble_enable(&app_ram_needed);
  if (enable_error == NRF_ERROR_NO_MEM) {
    Serial.printf(
        "*** ERR=sd_ble_enable code=NO_MEM alloc=0x%x, needed=0x%x\n",
        app_ram_base, app_ram_needed);
    return;
  } else if (enable_error != NRF_SUCCESS) {
    Serial.printf("*** ERR=sd_ble_enable code=0x%x\n", enable_error);
    return;
  }

  const auto power_error = sd_ble_gap_tx_power_set(
      BLE_GAP_TX_POWER_ROLE_SCAN_INIT, 0, +8);
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
          max_event_size, event_size);
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
            handle, &event->evt.gap_evt.params.conn_param_update_request);
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
        Serial.printf("ble_event=%d conn=%d\n", event->header.evt_id, handle);
        break;
    }
  }

  static const ble_gap_scan_params_t scan_params = {
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
        report->type.extended_pdu ? 'X' : 'x');
    if (flags) {
      Serial.printf(
          " f=%c%c",
          (flags & BLE_GAP_ADV_FLAG_LE_LIMITED_DISC_MODE) ? 'l' :
          (flags & BLE_GAP_ADV_FLAG_LE_GENERAL_DISC_MODE) ? 'G' : '.',
          (flags & BLE_GAP_ADV_FLAG_BR_EDR_NOT_SUPPORTED) ? 'x' :
          (flags & BLE_GAP_ADV_FLAG_LE_BR_EDR_CONTROLLER) ? 'C' :
          (flags & BLE_GAP_ADV_FLAG_LE_BR_EDR_HOST) ? 'H' : '?');
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
  Serial.printf(" handle=%d\n", h);
}

static void on_bt_disconn(uint16_t h, const ble_gap_evt_disconnected_t *dc) {
  Serial.printf("disconn conn=%d reason=0x%02x\n", h, dc->reason);
}

static void on_bt_update_request(
    uint16_t h, const ble_gap_evt_conn_param_update_request_t *request) {
  const auto *params = &request->conn_params;
  Serial.printf(
      "update_req conn=%d min_conn=%d max_conn=%d latency=%d conn_sup=%d\n",
      h, params->min_conn_interval, params->max_conn_interval,
      params->slave_latency, params->conn_sup_timeout);
}

static void on_bt_timeout(uint16_t h, const ble_gap_evt_timeout_t *timeout) {
  switch (timeout->src) {
    case BLE_GAP_TIMEOUT_SRC_SCAN:
      Serial.printf("*** scan_timeout\n");
      break;
    case BLE_GAP_TIMEOUT_SRC_CONN:
      Serial.printf("*** conn_fail timeout\n");
      break;
    case BLE_GAP_TIMEOUT_SRC_AUTH_PAYLOAD:
      Serial.printf("*** auth_timeout conn=%d\n", h);
      break;
    default:
      Serial.printf("*** timeout src=%d\n", timeout->src);
      break;
  }
}

static void on_bt_read_reply(const ble_gattc_evt_t *e) {
  if (e->gatt_status == BLE_GATT_STATUS_SUCCESS) {
    const auto *rr = &e->params.read_rsp;
    Serial.printf("read conn=%d attr=%d data=", e->conn_handle, rr->handle);
    print_escaped(rr->data, rr->len);
    Serial.println();
  } else {
    Serial.printf(
        "*** read_fail conn=%d attr=%d status=0x%x\n",
        e->conn_handle, e->error_handle, e->gatt_status);
  }
}

static void on_bt_write_done(const ble_gattc_evt_t *e) {
  if (e->gatt_status == BLE_GATT_STATUS_SUCCESS) {
    const auto *wr = &e->params.write_cmd_tx_complete;
    Serial.printf("write conn=%d done=%d\n", e->conn_handle, wr->count);
  } else {
    Serial.printf(
        "*** write_fail conn=%d attr=%d status=0x%x\n",
        e->conn_handle, e->error_handle, e->gatt_status);
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
          pc, ((SourceLoc *) info)->line, ((SourceLoc *) info)->file);
      break;
    default:
      Serial.printf("*** ERR=ble_fault code=0x%x PC=0x%08x\n", id, pc);
      break;
  }

  // 1/sec quick flash for softdevice fault.
  while (true) {
    digitalWrite(LED_BUILTIN, true);
    delay(50);
    digitalWrite(LED_BUILTIN, false);
    delay(950);
  }
}

static void print_address(const ble_gap_addr_t *addr) {
  if (addr->addr_type == BLE_GAP_ADDR_TYPE_ANONYMOUS) {
    Serial.print("anon");
  } else {
    const auto &a = addr->addr;
    Serial.printf(
        "%02x:%02x:%02x:%02x:%02x:%02x", a[5], a[4], a[3], a[2], a[1], a[0]);
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

static char *split_word(char **str) {
  while (isspace(**str)) ++*str;
  char *begin = *str;
  while (**str && !isspace(**str)) ++*str;
  while (**str && isspace(**str)) *(*str)++ = '\0';
  return begin;
}

static int decode_escaped(char *str) {
  char *out = str, *in = str;
  while (*in) {
    if (*in == '%' && isxdigit(in[1]) && isxdigit(in[2])) {
      const char hex[] = {in[1], in[2], 0};
      *out++ = strtoul(hex, NULL, 16);
      in += 3;
    } else {
      *out++ = *in++;
    }
  }
  *out = '\0';
  return out - str;
}

static void print_escaped(const void *data, int size) {
  for (int i = 0; i < size; ++i) {
    const auto b = ((const uint8_t *) data)[i];
    if (b > 32 && b < 128 && b != '%' && b != '"') {
      Serial.write(b);
    } else {
      Serial.printf("%%%02x", b);
    }
  }
}
