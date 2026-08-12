# UI action register

## Scope and result

This register maps every recognized UI event handler in the 1.5.8 application ELF
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.

It found **1128 handlers in 198 units**: 947 bound `onX` expressions and 181
declared callbacks. Each entry records its trigger, owner, named operations, effect
area, consequence, and Nuve Local status.

Action-corpus SHA-256:
`3efcf12511071e2feef47da89da6ee4ccc5fa73ec2f48f8633d8087a95876b24`.
QV4 unit-corpus SHA-256:
`b0f2bbb2bad5c537ce4addf739c9bebed67ae974b3a09fdbbe864ed7b66be788`.

The register maps encoded UI operations, not runtime success or electrical effects.
Nine handlers contain only context and return instructions. Subsystem pages cover
high-risk behavior.

## Construction rule

An action is a QML script-binding property or object-owned compiled function matching
`^on[A-Z][A-Za-z0-9_]*$`. The register follows `LoadClosure` targets within each unit
and derives stable IDs from unit and function coordinates.

Only operation names and counts are retained. Source text, compiled bodies,
translations, credentials, device data, and endpoint values are excluded. Domain
tags help search the register; they are not call-graph proof.

The private corpus holds the full action-level JSON. This summary includes counts,
action-bearing units, effect-free handlers, and reviewed indexed writes.

## Coverage

| Measure | Count |
|---|---:|
| QV4 units | 308 |
| Action-bearing units | 198 |
| Units without a recognized handler | 110 |
| Registered actions | 1128 |
| Identifier-level maps | 1119 |
| Effect-free stubs | 9 |
| No-identifier unknowns | 0 |
| Operation-level maps | 1128 |
| Unresolved dynamic/indexed effect targets | 0 |

### Trigger classes

| Class | Count |
|---|---:|
| `custom-signal` | 47 |
| `lifecycle` | 96 |
| `signal-callback` | 182 |
| `state-change` | 162 |
| `timer` | 119 |
| `user-input` | 522 |

### Consequence dispositions

| Class | Count |
|---|---:|
| `diagnostic-local-indexed-state` | 3 |
| `effect-free` | 9 |
| `local-computation-or-read` | 1 |
| `named-effect-boundary` | 1115 |

### Effect-domain tags

| Class | Count |
|---|---:|
| `application-lifecycle` | 6 |
| `application-state` | 4 |
| `application-ui-state` | 64 |
| `diagnostic-test` | 101 |
| `display-power` | 58 |
| `equipment-test` | 42 |
| `factory-reset` | 6 |
| `hvac-setting` | 203 |
| `installer-service` | 146 |
| `lock-access` | 25 |
| `message-popup` | 397 |
| `navigation` | 96 |
| `network-wifi` | 99 |
| `none` | 9 |
| `performance-test` | 9 |
| `persistence` | 32 |
| `remote-api` | 61 |
| `schedule` | 162 |
| `sensor-radio` | 34 |
| `service-control` | 2 |
| `software-update` | 35 |
| `storage-maintenance` | 6 |
| `system-clock` | 17 |
| `ui-local-state` | 56 |
| `weather` | 4 |

### Nuve Local integration dispositions

| Class | Count |
|---|---:|
| `firmware-ui-evidence-only` | 619 |
| `unsupported-diagnostic` | 101 |
| `unsupported-equipment-test` | 42 |
| `unsupported-installer` | 146 |
| `unsupported-lock` | 25 |
| `unsupported-performance-test` | 9 |
| `unsupported-reset` | 6 |
| `unsupported-schedule` | 162 |
| `unsupported-service-control` | 2 |
| `unsupported-storage-maintenance` | 6 |
| `unsupported-system-clock` | 17 |
| `unsupported-update` | 35 |

Counts can overlap when one handler enters several families. Nuve Local does not
support schedule, lock, reset, update, installer, diagnostic, equipment-test,
service-control, storage-maintenance, or system-clock actions.

See [Scheduling](scheduling-protocol.md), [Screen lock](lock-protocol.md),
[Application update](application-update.md),
[Installer APIs](installer-private-api.md), and
[Equipment test](performance-test.md) for subsystem details.

## Action-bearing unit register

`Unit` is the ELF symbol suffix; firmware spelling errors are preserved. `U` counts
handlers without an identifier map or effect-free body. It is zero here.

| Exact unit | Category | Actions | U | Trigger counts | Effect domains |
|---|---|---:|---:|---|---|
| `_0x5f_Stherm_Main_qml` | `application-root` | 6 | 0 | lifecycle=2, signal-callback=1, state-change=2, timer=1 | application-lifecycle |
| `_0x5f_Stherm_qml_Core_DeviceController_qml` | `core-controller` | 93 | 0 | custom-signal=3, lifecycle=1, signal-callback=63, timer=26 | application-state, display-power, equipment-test, factory-reset, hvac-setting, installer-service, lock-access, message-popup, navigation, network-wifi, persistence, remote-api, schedule, sensor-radio, service-control, software-update, system-clock |
| `_0x5f_Stherm_qml_Core_MessageController_qml` | `core-controller` | 24 | 0 | lifecycle=1, signal-callback=15, timer=8 | display-power, installer-service, message-popup, network-wifi, persistence, remote-api, sensor-radio, software-update |
| `_0x5f_Stherm_qml_Core_ScheduleControllerV2_qml` | `core-controller` | 20 | 0 | lifecycle=1, signal-callback=9, state-change=3, timer=7 | hvac-setting, network-wifi, persistence, remote-api, schedule |
| `_0x5f_Stherm_qml_Core_SchedulesController_qml` | `core-controller` | 17 | 0 | lifecycle=1, signal-callback=9, state-change=1, timer=6 | hvac-setting, network-wifi, persistence, remote-api, schedule |
| `_0x5f_Stherm_qml_Core_SensorController_qml` | `core-controller` | 1 | 0 | lifecycle=1 | sensor-radio |
| `_0x5f_Stherm_qml_UiCore_Components_AppHeader_qml` | `application-component` | 2 | 0 | user-input=2 | application-ui-state |
| `_0x5f_Stherm_qml_UiCore_Components_ColorSlider_qml` | `application-component` | 1 | 0 | state-change=1 | application-ui-state |
| `_0x5f_Stherm_qml_UiCore_Components_DateTimeLabel_qml` | `application-component` | 1 | 0 | signal-callback=1 | application-ui-state |
| `_0x5f_Stherm_qml_UiCore_Components_FanButton_qml` | `application-component` | 5 | 0 | signal-callback=3, timer=2 | hvac-setting |
| `_0x5f_Stherm_qml_UiCore_Components_ManualButtons_qml` | `application-component` | 8 | 0 | lifecycle=1, state-change=2, user-input=5 | hvac-setting |
| `_0x5f_Stherm_qml_UiCore_Components_PINKeyboard_qml` | `application-component` | 10 | 0 | custom-signal=1, lifecycle=1, state-change=2, timer=2, user-input=4 | lock-access |
| `_0x5f_Stherm_qml_UiCore_Components_SelectFanDurationSection_qml` | `application-component` | 1 | 0 | user-input=1 | hvac-setting |
| `_0x5f_Stherm_qml_UiCore_Components_SoftwareChangeLog_qml` | `application-component` | 1 | 0 | user-input=1 | software-update |
| `_0x5f_Stherm_qml_UiCore_Components_SystemModeButton_qml` | `application-component` | 3 | 0 | signal-callback=2, timer=1 | hvac-setting |
| `_0x5f_Stherm_qml_UiCore_Components_TemperatureStepperControl_qml` | `application-component` | 2 | 0 | user-input=2 | hvac-setting |
| `_0x5f_Stherm_qml_UiCore_Components_TimeTumblers_qml` | `application-component` | 4 | 0 | state-change=4 | application-ui-state |
| `_0x5f_Stherm_qml_UiCore_Components_ToastListView_qml` | `application-component` | 7 | 0 | lifecycle=1, signal-callback=5, state-change=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_Components_VirtualKeyboardControl_qml` | `application-component` | 44 | 0 | state-change=4, timer=2, user-input=38 | application-ui-state, display-power, message-popup |
| `_0x5f_Stherm_qml_UiCore_I_Dialog_qml` | `ui-infrastructure` | 3 | 0 | user-input=3 | ui-local-state |
| `_0x5f_Stherm_qml_UiCore_I_PopUp_qml` | `ui-infrastructure` | 4 | 0 | lifecycle=3, user-input=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_I_PopUp2_qml` | `ui-infrastructure` | 5 | 0 | lifecycle=3, user-input=2 | message-popup, none |
| `_0x5f_Stherm_qml_UiCore_PopUpLayout_qml` | `ui-infrastructure` | 1 | 0 | signal-callback=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_AlertNotifPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_CalibratingPopup_qml` | `application-popup` | 1 | 0 | timer=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_ConfirmPopup_qml` | `application-popup` | 5 | 0 | user-input=5 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_CopySchedulePopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, schedule |
| `_0x5f_Stherm_qml_UiCore_PopUps_CountDownPopup_qml` | `application-popup` | 3 | 0 | state-change=1, timer=1, user-input=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_CriticalErrorDiagnosticsPopup_qml` | `application-popup` | 4 | 0 | lifecycle=2, user-input=2 | message-popup, network-wifi |
| `_0x5f_Stherm_qml_UiCore_PopUps_ErrorPopup_qml` | `application-popup` | 1 | 0 | user-input=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_HoldPopup_qml` | `application-popup` | 4 | 0 | timer=1, user-input=3 | message-popup, persistence |
| `_0x5f_Stherm_qml_UiCore_PopUps_HumidityControlPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, persistence |
| `_0x5f_Stherm_qml_UiCore_PopUps_InfoPopup_qml` | `application-popup` | 1 | 0 | user-input=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_InstallConfirmationPopup_qml` | `application-popup` | 1 | 0 | timer=1 | message-popup, software-update |
| `_0x5f_Stherm_qml_UiCore_PopUps_InvalidZipCodePopup_qml` | `application-popup` | 2 | 0 | state-change=1, user-input=1 | installer-service, message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_LimitedInitialSetupPopup_qml` | `application-popup` | 5 | 0 | user-input=5 | installer-service, message-popup, network-wifi |
| `_0x5f_Stherm_qml_UiCore_PopUps_ManualDateTimeWarningPopup_qml` | `application-popup` | 2 | 0 | lifecycle=2 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_NoWifiAlternativeFlowPopup_qml` | `application-popup` | 3 | 0 | lifecycle=1, user-input=2 | installer-service, lock-access, message-popup, network-wifi |
| `_0x5f_Stherm_qml_UiCore_PopUps_PerfTestPopup_qml` | `application-popup` | 3 | 0 | signal-callback=1, user-input=2 | equipment-test, hvac-setting, message-popup, performance-test, schedule |
| `_0x5f_Stherm_qml_UiCore_PopUps_ResetFactoryPopUp_qml` | `application-popup` | 2 | 0 | user-input=2 | factory-reset, message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_ScheduleMigrationPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, schedule |
| `_0x5f_Stherm_qml_UiCore_PopUps_ScheduleOverlapPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, schedule |
| `_0x5f_Stherm_qml_UiCore_PopUps_ScheduleSystemModeErrorPopup_qml` | `application-popup` | 1 | 0 | user-input=1 | hvac-setting, message-popup, schedule |
| `_0x5f_Stherm_qml_UiCore_PopUps_SendingLogPopup_qml` | `application-popup` | 2 | 0 | signal-callback=2 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_SkipWIFIConnectionPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, network-wifi |
| `_0x5f_Stherm_qml_UiCore_PopUps_SleepDisplaySettingsPopup_qml` | `application-popup` | 9 | 0 | lifecycle=2, state-change=1, user-input=6 | hvac-setting, message-popup, persistence |
| `_0x5f_Stherm_qml_UiCore_PopUps_SuccessPopup_qml` | `application-popup` | 1 | 0 | user-input=1 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_SwitchHeatingPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_TempratureUnitPopup_qml` | `application-popup` | 2 | 0 | timer=1, user-input=1 | message-popup, persistence |
| `_0x5f_Stherm_qml_UiCore_PopUps_TestEquipmentPopup_qml` | `application-popup` | 1 | 0 | lifecycle=1 | equipment-test, message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_TestFailedPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_ThermostatNamePopup_qml` | `application-popup` | 4 | 0 | state-change=2, user-input=2 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_TimeFormatPopup_qml` | `application-popup` | 3 | 0 | timer=1, user-input=2 | message-popup |
| `_0x5f_Stherm_qml_UiCore_PopUps_UpdateInterruptionPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, network-wifi, software-update |
| `_0x5f_Stherm_qml_UiCore_PopUps_UpdateNotificationPopup_qml` | `application-popup` | 2 | 0 | user-input=2 | message-popup, software-update |
| `_0x5f_Stherm_qml_UiCore_PopUps_WarrantyReplacementPopup_qml` | `application-popup` | 10 | 0 | signal-callback=2, state-change=5, timer=2, user-input=1 | installer-service, message-popup, network-wifi, remote-api |
| `_0x5f_Stherm_qml_UiCore_ShortcutManager_qml` | `ui-infrastructure` | 3 | 0 | user-input=3 | persistence, ui-local-state |
| `_0x5f_Stherm_qml_UiCore_SimpleStackView_qml` | `ui-infrastructure` | 1 | 0 | lifecycle=1 | ui-local-state |
| `_0x5f_Stherm_qml_UiCore_UiSession_qml` | `ui-infrastructure` | 4 | 0 | custom-signal=3, lifecycle=1 | display-power, hvac-setting, message-popup, navigation, network-wifi, persistence, remote-api |
| `_0x5f_Stherm_qml_UiCore_UiSessionPopups_qml` | `ui-infrastructure` | 44 | 0 | custom-signal=5, lifecycle=8, signal-callback=18, timer=4, user-input=9 | display-power, equipment-test, hvac-setting, installer-service, message-popup, navigation, network-wifi, performance-test, persistence, schedule, sensor-radio, software-update |
| `_0x5f_Stherm_qml_View_AboutDevicePage_qml` | `application-view` | 10 | 0 | custom-signal=1, signal-callback=3, user-input=6 | application-ui-state, message-popup, navigation, network-wifi, none |
| `_0x5f_Stherm_qml_View_AddSchedulePage_qml` | `application-view` | 15 | 0 | custom-signal=1, lifecycle=1, state-change=9, user-input=4 | message-popup, navigation, schedule |
| `_0x5f_Stherm_qml_View_AnimatedSplash_qml` | `application-view` | 1 | 0 | state-change=1 | application-ui-state |
| `_0x5f_Stherm_qml_View_BackdoorUpdatePage_qml` | `application-view` | 5 | 0 | state-change=1, user-input=4 | navigation, software-update |
| `_0x5f_Stherm_qml_View_BacklightPage_qml` | `application-view` | 12 | 0 | lifecycle=1, state-change=4, timer=1, user-input=6 | display-power, message-popup, navigation |
| `_0x5f_Stherm_qml_View_BasePageView_qml` | `application-view` | 4 | 0 | user-input=4 | application-ui-state |
| `_0x5f_Stherm_qml_View_ContactContractorPage_qml` | `application-view` | 1 | 0 | user-input=1 | installer-service, navigation |
| `_0x5f_Stherm_qml_View_ContractorInformationFinishPage_qml` | `application-view` | 6 | 0 | custom-signal=2, lifecycle=1, signal-callback=1, user-input=2 | installer-service, message-popup, network-wifi |
| `_0x5f_Stherm_qml_View_ContractorInformationPage_qml` | `application-view` | 6 | 0 | lifecycle=1, signal-callback=1, state-change=1, timer=1, user-input=2 | installer-service, network-wifi |
| `_0x5f_Stherm_qml_View_DateTime_DateTimePage_qml` | `application-view` | 8 | 0 | lifecycle=2, state-change=1, user-input=5 | message-popup, persistence, remote-api, system-clock |
| `_0x5f_Stherm_qml_View_DateTime_SelectDatePopup_qml` | `application-view` | 7 | 0 | user-input=7 | message-popup |
| `_0x5f_Stherm_qml_View_DateTime_SelectTimePopup_qml` | `application-view` | 4 | 0 | lifecycle=1, state-change=2, user-input=1 | message-popup |
| `_0x5f_Stherm_qml_View_DateTime_SelectTimezonePage_qml` | `application-view` | 2 | 0 | lifecycle=1, user-input=1 | system-clock |
| `_0x5f_Stherm_qml_View_DateTime_SelectTimezonePopup_qml` | `application-view` | 2 | 0 | lifecycle=1, user-input=1 | message-popup, system-clock |
| `_0x5f_Stherm_qml_View_Delegates_ScheduleDelegate_qml` | `application-view` | 3 | 0 | custom-signal=1, user-input=2 | hvac-setting, message-popup, persistence, schedule |
| `_0x5f_Stherm_qml_View_Delegates_WifiDelegate_qml` | `application-view` | 1 | 0 | user-input=1 | network-wifi |
| `_0x5f_Stherm_qml_View_DevelopmentModePage_qml` | `application-view` | 18 | 0 | signal-callback=5, user-input=13 | factory-reset, installer-service, message-popup, navigation, network-wifi, remote-api, sensor-radio, service-control |
| `_0x5f_Stherm_qml_View_FanPopup_qml` | `application-view` | 2 | 0 | user-input=2 | message-popup, persistence, schedule |
| `_0x5f_Stherm_qml_View_Home_qml` | `application-view` | 36 | 0 | custom-signal=2, lifecycle=3, signal-callback=11, state-change=5, timer=2, user-input=13 | application-ui-state, hvac-setting, installer-service, message-popup, navigation, network-wifi, none, remote-api, schedule, system-clock, weather |
| `_0x5f_Stherm_qml_View_InitialSetup_ScanQRPage_qml` | `application-view` | 3 | 0 | state-change=2, timer=1 | installer-service, lock-access |
| `_0x5f_Stherm_qml_View_InitialSetupViewer_qml` | `application-view` | 17 | 0 | custom-signal=7, state-change=1, timer=1, user-input=8 | hvac-setting, installer-service, message-popup, navigation, network-wifi |
| `_0x5f_Stherm_qml_View_LockPage_qml` | `application-view` | 1 | 0 | custom-signal=1 | lock-access, navigation |
| `_0x5f_Stherm_qml_View_MainView_qml` | `application-view` | 11 | 0 | custom-signal=2, lifecycle=2, signal-callback=3, state-change=2, timer=1, user-input=1 | display-power, installer-service, lock-access, message-popup, navigation, network-wifi, performance-test, persistence, software-update |
| `_0x5f_Stherm_qml_View_Menu_AppMenuPage_qml` | `application-view` | 5 | 0 | user-input=5 | hvac-setting, installer-service, message-popup, navigation, remote-api, schedule |
| `_0x5f_Stherm_qml_View_Menu_LimitedModeRemainigTimePage_qml` | `application-view` | 5 | 0 | lifecycle=1, user-input=4 | hvac-setting, navigation |
| `_0x5f_Stherm_qml_View_Menu_ManageEndpoint_qml` | `application-view` | 5 | 0 | lifecycle=1, user-input=4 | navigation, remote-api |
| `_0x5f_Stherm_qml_View_Menu_MenuGroupItem_qml` | `application-view` | 2 | 0 | user-input=2 | application-ui-state |
| `_0x5f_Stherm_qml_View_Menu_MenuListView_qml` | `application-view` | 1 | 0 | custom-signal=1 | application-ui-state |
| `_0x5f_Stherm_qml_View_Menu_MessagesPage_qml` | `application-view` | 2 | 0 | custom-signal=1, user-input=1 | message-popup, persistence, remote-api |
| `_0x5f_Stherm_qml_View_Menu_NotificationBasePage_qml` | `application-view` | 2 | 0 | user-input=2 | message-popup, navigation |
| `_0x5f_Stherm_qml_View_Menu_SettingsMenuPage_qml` | `application-view` | 10 | 0 | custom-signal=1, user-input=9 | hvac-setting, installer-service, message-popup, navigation, network-wifi, performance-test, software-update |
| `_0x5f_Stherm_qml_View_Menu_StorageManagerPage_qml` | `application-view` | 6 | 0 | signal-callback=1, timer=1, user-input=4 | message-popup, storage-maintenance |
| `_0x5f_Stherm_qml_View_Menu_ZipCodeEditPage_qml` | `application-view` | 10 | 0 | signal-callback=2, state-change=1, timer=3, user-input=4 | display-power, installer-service, message-popup, navigation, network-wifi |
| `_0x5f_Stherm_qml_View_MessagePopupView_qml` | `application-view` | 11 | 0 | lifecycle=4, signal-callback=6, user-input=1 | installer-service, message-popup, navigation, network-wifi, persistence, remote-api |
| `_0x5f_Stherm_qml_View_MobileAppPage_qml` | `application-view` | 2 | 0 | lifecycle=1, user-input=1 | remote-api |
| `_0x5f_Stherm_qml_View_PrivacyPolicyPage_qml` | `application-view` | 4 | 0 | timer=1, user-input=3 | application-ui-state, message-popup |
| `_0x5f_Stherm_qml_View_RequestTechPriorityPage_qml` | `application-view` | 3 | 0 | user-input=3 | none |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleDataSourcePage_qml` | `application-view` | 1 | 0 | user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleHumidityPage_qml` | `application-view` | 1 | 0 | user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleNamePage_qml` | `application-view` | 3 | 0 | timer=1, user-input=2 | schedule |
| `_0x5f_Stherm_qml_View_Schedule_SchedulePreviewPage_qml` | `application-view` | 13 | 0 | lifecycle=1, state-change=2, user-input=10 | schedule |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleRepeatPage_qml` | `application-view` | 2 | 0 | state-change=1, user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleTempraturePage_qml` | `application-view` | 2 | 0 | lifecycle=1, user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleTimePage_qml` | `application-view` | 4 | 0 | lifecycle=1, state-change=2, user-input=1 | message-popup, schedule |
| `_0x5f_Stherm_qml_View_Schedule_ScheduleTypePage_qml` | `application-view` | 1 | 0 | user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_AddSchedulePageV2_qml` | `application-view` | 2 | 0 | user-input=2 | navigation, schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_AddSchedulePageV2_ScheduleConfigPage_qml` | `application-view` | 1 | 0 | timer=1 | message-popup, schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_AddSchedulePageV2_SelectScheduleDaysPage_qml` | `application-view` | 1 | 0 | user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_HoldLabel_qml` | `application-view` | 4 | 0 | signal-callback=1, state-change=1, timer=1, user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_HoldScheduleV2Popup_qml` | `application-view` | 1 | 0 | user-input=1 | message-popup, schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_ScheduleDelegateV2_qml` | `application-view` | 1 | 0 | user-input=1 | schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_SchedulePreviewPageV2_qml` | `application-view` | 16 | 0 | lifecycle=1, state-change=6, timer=1, user-input=8 | hvac-setting, message-popup, navigation, schedule |
| `_0x5f_Stherm_qml_View_ScheduleV2_ScheduleViewV2_qml` | `application-view` | 15 | 0 | custom-signal=1, lifecycle=3, signal-callback=2, state-change=1, user-input=8 | message-popup, navigation, persistence, schedule |
| `_0x5f_Stherm_qml_View_ScheduleView_qml` | `application-view` | 15 | 0 | custom-signal=3, lifecycle=3, user-input=9 | hvac-setting, message-popup, navigation, schedule |
| `_0x5f_Stherm_qml_View_ScreenSaver_qml` | `application-view` | 2 | 0 | lifecycle=1, timer=1 | display-power |
| `_0x5f_Stherm_qml_View_Sensor_AddSensorPage_qml` | `application-view` | 5 | 0 | custom-signal=2, lifecycle=1, user-input=2 | sensor-radio |
| `_0x5f_Stherm_qml_View_Sensor_SensorInfoPage_qml` | `application-view` | 5 | 0 | lifecycle=2, user-input=3 | navigation, sensor-radio |
| `_0x5f_Stherm_qml_View_Sensor_SensorPairPage_qml` | `application-view` | 3 | 0 | timer=2, user-input=1 | display-power, sensor-radio |
| `_0x5f_Stherm_qml_View_SensorsPage_qml` | `application-view` | 2 | 0 | user-input=2 | sensor-radio |
| `_0x5f_Stherm_qml_View_ServiceTitan_CustomerDetailsPage_qml` | `application-view` | 1 | 0 | user-input=1 | installer-service |
| `_0x5f_Stherm_qml_View_ServiceTitan_InitialSetupBasePageView_qml` | `application-view` | 2 | 0 | user-input=2 | installer-service |
| `_0x5f_Stherm_qml_View_ServiceTitan_JobNumberPage_qml` | `application-view` | 9 | 0 | signal-callback=1, state-change=2, timer=2, user-input=4 | installer-service, message-popup, network-wifi, remote-api |
| `_0x5f_Stherm_qml_View_ServiceTitan_ServiceTitanReviewPage_qml` | `application-view` | 5 | 0 | signal-callback=1, state-change=1, timer=2, user-input=1 | installer-service, message-popup, network-wifi |
| `_0x5f_Stherm_qml_View_ServiceTitan_WarrantyReplacementPage_qml` | `application-view` | 9 | 0 | signal-callback=1, state-change=3, timer=2, user-input=3 | installer-service, message-popup, network-wifi, remote-api |
| `_0x5f_Stherm_qml_View_SettingsPage_qml` | `application-view` | 14 | 0 | lifecycle=2, state-change=3, timer=2, user-input=7 | display-power, hvac-setting, message-popup, navigation, persistence |
| `_0x5f_Stherm_qml_View_SplashScreen_qml` | `application-view` | 1 | 0 | timer=1 | application-ui-state |
| `_0x5f_Stherm_qml_View_SystemMode_SelectModeSection_qml` | `application-view` | 1 | 0 | user-input=1 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemMode_VacationModePage_qml` | `application-view` | 1 | 0 | user-input=1 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemModePage_qml` | `application-view` | 13 | 0 | custom-signal=1, lifecycle=1, state-change=1, user-input=10 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemModePopup_qml` | `application-view` | 7 | 0 | state-change=4, user-input=3 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_DeviceLocationPage_qml` | `application-view` | 1 | 0 | user-input=1 | installer-service |
| `_0x5f_Stherm_qml_View_SystemSetup_DualFuelHeatingPage_qml` | `application-view` | 2 | 0 | timer=1, user-input=1 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_InstallationTypePage_qml` | `application-view` | 2 | 0 | user-input=2 | installer-service |
| `_0x5f_Stherm_qml_View_SystemSetup_ResidenceTypePage_qml` | `application-view` | 1 | 0 | user-input=1 | installer-service |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemAccessoriesPage_qml` | `application-view` | 6 | 0 | user-input=6 | hvac-setting, message-popup, navigation |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemAgePage_qml` | `application-view` | 2 | 0 | lifecycle=1, state-change=1 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemDissipationTimePage_qml` | `application-view` | 4 | 0 | user-input=4 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemGeneralThresholdsPage_qml` | `application-view` | 6 | 0 | user-input=6 | installer-service, navigation |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemMinimumOnTimePage_qml` | `application-view` | 4 | 0 | user-input=4 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemOverCoolToDehumidify_qml` | `application-view` | 4 | 0 | user-input=4 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemRunDelayPage_qml` | `application-view` | 7 | 0 | user-input=7 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTemperatureCorrectionPage_qml` | `application-view` | 6 | 0 | lifecycle=1, state-change=1, user-input=4 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTemperatureDifferentialPage_qml` | `application-view` | 4 | 0 | user-input=4 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTypeCoolOnlyPage_qml` | `application-view` | 1 | 0 | user-input=1 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTypeHeatOnlyPage_qml` | `application-view` | 1 | 0 | user-input=1 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTypeHeatPumpPage_qml` | `application-view` | 2 | 0 | timer=1, user-input=1 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTypePage_qml` | `application-view` | 6 | 0 | user-input=6 | hvac-setting, installer-service, navigation |
| `_0x5f_Stherm_qml_View_SystemSetup_SystemTypeTraditionPage_qml` | `application-view` | 1 | 0 | user-input=1 | hvac-setting |
| `_0x5f_Stherm_qml_View_SystemSetup_TestEquipmentPage_qml` | `application-view` | 12 | 0 | signal-callback=1, state-change=8, timer=2, user-input=1 | equipment-test, message-popup, navigation |
| `_0x5f_Stherm_qml_View_SystemSetup_ThermostatNamePage_qml` | `application-view` | 2 | 0 | user-input=2 | application-ui-state, installer-service, network-wifi, persistence |
| `_0x5f_Stherm_qml_View_SystemSetupPage_qml` | `application-view` | 7 | 0 | lifecycle=2, user-input=5 | equipment-test, hvac-setting, message-popup, navigation, persistence |
| `_0x5f_Stherm_qml_View_SystemUpdatePage_qml` | `application-view` | 7 | 0 | lifecycle=2, user-input=5 | message-popup, navigation, software-update |
| `_0x5f_Stherm_qml_View_Test_AudioTestPage_qml` | `diagnostic-page` | 2 | 0 | user-input=2 | diagnostic-test, none |
| `_0x5f_Stherm_qml_View_Test_BacklightTestPage_qml` | `diagnostic-page` | 9 | 0 | state-change=1, timer=1, user-input=7 | diagnostic-test, display-power, message-popup, navigation |
| `_0x5f_Stherm_qml_View_Test_BrightnessTestPage_qml` | `diagnostic-page` | 11 | 0 | lifecycle=1, state-change=1, timer=1, user-input=8 | diagnostic-test, display-power, message-popup, navigation |
| `_0x5f_Stherm_qml_View_Test_ColorTestPage_qml` | `diagnostic-page` | 8 | 0 | state-change=1, timer=2, user-input=5 | diagnostic-test, message-popup |
| `_0x5f_Stherm_qml_View_Test_InternalSensorTestPage_qml` | `diagnostic-page` | 9 | 0 | lifecycle=1, state-change=1, timer=2, user-input=5 | diagnostic-test, navigation |
| `_0x5f_Stherm_qml_View_Test_QRCodeTestPage_qml` | `diagnostic-page` | 10 | 0 | signal-callback=2, timer=3, user-input=5 | diagnostic-test, message-popup, navigation, network-wifi, remote-api |
| `_0x5f_Stherm_qml_View_Test_RelayTestPage_qml` | `diagnostic-page` | 23 | 0 | lifecycle=1, state-change=13, timer=2, user-input=7 | diagnostic-test, equipment-test, message-popup, navigation |
| `_0x5f_Stherm_qml_View_Test_StartTestPage_qml` | `diagnostic-page` | 5 | 0 | lifecycle=1, timer=2, user-input=2 | diagnostic-test, navigation, remote-api, sensor-radio, software-update |
| `_0x5f_Stherm_qml_View_Test_SystemUpdateOnTestModePage_qml` | `diagnostic-page` | 3 | 0 | lifecycle=1, state-change=1, user-input=1 | diagnostic-test, software-update |
| `_0x5f_Stherm_qml_View_Test_TestConfigPage_qml` | `diagnostic-page` | 4 | 0 | user-input=4 | diagnostic-test, navigation, remote-api |
| `_0x5f_Stherm_qml_View_Test_TestsHostPage_qml` | `diagnostic-page` | 1 | 0 | lifecycle=1 | diagnostic-test |
| `_0x5f_Stherm_qml_View_Test_TouchTestPage_qml` | `diagnostic-page` | 13 | 0 | custom-signal=1, lifecycle=1, state-change=5, timer=1, user-input=5 | diagnostic-test, message-popup |
| `_0x5f_Stherm_qml_View_Test_VersionInformationPage_qml` | `diagnostic-page` | 4 | 0 | lifecycle=1, timer=1, user-input=2 | diagnostic-test, navigation |
| `_0x5f_Stherm_qml_View_UnlockPage_qml` | `application-view` | 4 | 0 | custom-signal=2, lifecycle=1, user-input=1 | installer-service, lock-access, message-popup |
| `_0x5f_Stherm_qml_View_VacationModeView_qml` | `application-view` | 6 | 0 | lifecycle=1, state-change=1, timer=1, user-input=3 | hvac-setting, message-popup |
| `_0x5f_Stherm_qml_View_WeatherPage_qml` | `application-view` | 3 | 0 | lifecycle=1, user-input=2 | navigation, weather |
| `_0x5f_Stherm_qml_View_Wifi_WifiConnectPopup_qml` | `application-view` | 7 | 0 | signal-callback=4, state-change=1, timer=1, user-input=1 | installer-service, lock-access, message-popup, navigation, network-wifi |
| `_0x5f_Stherm_qml_View_Wifi_WifiInfoPopup_qml` | `application-view` | 3 | 0 | lifecycle=1, user-input=2 | message-popup, network-wifi |
| `_0x5f_Stherm_qml_View_Wifi_WifiManualConnectPopup_qml` | `application-view` | 10 | 0 | signal-callback=1, state-change=8, user-input=1 | message-popup, network-wifi |
| `_0x5f_Stherm_qml_View_WifiPage_qml` | `application-view` | 17 | 0 | custom-signal=3, lifecycle=2, signal-callback=3, state-change=1, timer=1, user-input=7 | installer-service, message-popup, navigation, network-wifi, none |
| `_0x5f_Stherm_qml_View_WiringPage_qml` | `application-view` | 12 | 0 | user-input=12 | hvac-setting |
| `_0x5f_Ronia_AirbnbPageIndicator_qml` | `ui-toolkit` | 1 | 0 | state-change=1 | ui-local-state |
| `_0x5f_Ronia_CircularSliderDoubleHandle_qml` | `ui-toolkit` | 9 | 0 | state-change=7, user-input=2 | ui-local-state |
| `_0x5f_Ronia_ComboBox_qml` | `ui-toolkit` | 1 | 0 | user-input=1 | message-popup |
| `_0x5f_Ronia_ConfirmationDialog_qml` | `ui-toolkit` | 3 | 0 | user-input=3 | ui-local-state |
| `_0x5f_Ronia_Dialog_qml` | `ui-toolkit` | 1 | 0 | user-input=1 | ui-local-state |
| `_0x5f_Ronia_Drawer_qml` | `ui-toolkit` | 4 | 0 | state-change=2, user-input=2 | message-popup, ui-local-state |
| `_0x5f_Ronia_EmptyState_qml` | `ui-toolkit` | 1 | 0 | user-input=1 | ui-local-state |
| `_0x5f_Ronia_ExpandableItem_qml` | `ui-toolkit` | 3 | 0 | user-input=3 | lock-access, ui-local-state |
| `_0x5f_Ronia_Flickable_qml` | `ui-toolkit` | 1 | 0 | state-change=1 | ui-local-state |
| `_0x5f_Ronia_Frame_qml` | `ui-toolkit` | 3 | 0 | user-input=3 | ui-local-state |
| `_0x5f_Ronia_GroupBox_qml` | `ui-toolkit` | 1 | 0 | user-input=1 | ui-local-state |
| `_0x5f_Ronia_ItemDelegate_qml` | `ui-toolkit` | 2 | 0 | user-input=2 | ui-local-state |
| `_0x5f_Ronia_LimitedRangeSlider_qml` | `ui-toolkit` | 1 | 0 | lifecycle=1 | ui-local-state |
| `_0x5f_Ronia_ListView_qml` | `ui-toolkit` | 1 | 0 | user-input=1 | ui-local-state |
| `_0x5f_Ronia_MessageDialog_qml` | `ui-toolkit` | 2 | 0 | lifecycle=1, timer=1 | message-popup |
| `_0x5f_Ronia_PasswordTextField_qml` | `ui-toolkit` | 1 | 0 | user-input=1 | lock-access |
| `_0x5f_Ronia_Ripple_qml` | `ui-toolkit` | 1 | 0 | state-change=1 | ui-local-state |
| `_0x5f_Ronia_SpinBox_qml` | `ui-toolkit` | 2 | 0 | user-input=2 | ui-local-state |
| `_0x5f_Ronia_TextField_qml` | `ui-toolkit` | 4 | 0 | custom-signal=1, state-change=1, user-input=2 | ui-local-state |
| `_0x5f_Ronia_Toast_qml` | `ui-toolkit` | 2 | 0 | timer=1, user-input=1 | message-popup |
| `_0x5f_Ronia_impl_RangeSliderHandles_qml` | `ui-toolkit` | 8 | 0 | state-change=8 | ui-local-state |
| `_0x5f_QtQuickStream_resources_Core_QSCore_qml` | `persistence-framework` | 2 | 0 | custom-signal=1, lifecycle=1 | persistence |
| `_0x5f_QtQuickStream_resources_Core_QSRepository_qml` | `persistence-framework` | 2 | 0 | state-change=2 | none, persistence |
| `_0x5f_QtQuickStream_resources_Core_QSUtil_qml` | `persistence-framework` | 1 | 0 | lifecycle=1 | persistence |
| `_0x5f_Ronia_impl_impl_RangeSliderHandles_qml` | `ui-toolkit` | 8 | 0 | state-change=8 | ui-local-state |

## Effect-free handler stubs

These handlers and their nested closures only load context or registers, return, and
clean up context. They do not read or write properties, call code, construct values,
branch, or emit signals.

| Stable ID | Exact unit | Owner | Handler | Line |
|---|---|---|---|---:|
| `ui-f3d3af298b81977a` | `_0x5f_QtQuickStream_resources_Core_QSRepository_qml` | `QSRepositoryCpp` | `onNameChanged` | 48 |
| `ui-2f74a1ddf87b5b41` | `_0x5f_Stherm_qml_UiCore_I_PopUp2_qml` | `unowned` | `onCompleted` | 110 |
| `ui-1f9c72aff7e14464` | `_0x5f_Stherm_qml_View_AboutDevicePage_qml` | `Button` | `onClicked` | 278 |
| `ui-56bbe8461b7e378b` | `_0x5f_Stherm_qml_View_Home_qml` | `TapHandler` | `onTapped` | 607 |
| `ui-8f14e0d5e0ac4b6f` | `_0x5f_Stherm_qml_View_RequestTechPriorityPage_qml` | `ToolButton` | `onClicked` | 28 |
| `ui-7fb715872de1b1f3` | `_0x5f_Stherm_qml_View_RequestTechPriorityPage_qml` | `Button` | `onClicked` | 52 |
| `ui-a6a893c8512f55a6` | `_0x5f_Stherm_qml_View_RequestTechPriorityPage_qml` | `Button` | `onClicked` | 63 |
| `ui-c0d33b0dfdb666e9` | `_0x5f_Stherm_qml_View_Test_AudioTestPage_qml` | `ToolButton` | `onClicked` | 40 |
| `ui-07ba7724a2725d29` | `_0x5f_Stherm_qml_View_WifiPage_qml` | `unowned` | `onCompleted` | 66 |

## Exact reviewed indexed writes

These diagnostic handlers write only to touch-test point and string arrays. Review
found no native, persistence, network, schedule, or HVAC call.

| Stable ID | Exact unit | Handler | Disposition |
|---|---|---|---|
| `ui-aab701d46b404c6d` | `_0x5f_Stherm_qml_View_Test_TouchTestPage_qml` | `onRadiusChanged` | `diagnostic-local-indexed-state` |
| `ui-3484face58e03f3e` | `_0x5f_Stherm_qml_View_Test_TouchTestPage_qml` | `onGrabChanged` | `diagnostic-local-indexed-state` |
| `ui-eea19fd0068068a6` | `_0x5f_Stherm_qml_View_Test_TouchTestPage_qml` | `onActiveTranslationChanged` | `diagnostic-local-indexed-state` |

## No-identifier unknowns

These handlers have no resolvable identifier or effect-free body. Resolve them with
instruction review, isolated emulation, or an approved live observation.

| Stable ID | Exact unit | Owner | Handler | Line |
|---|---|---|---|---:|

## Reproduction

Generate the private schema-v4 QV4 inventory and then this register:

```bash
.venv/bin/python .agents/skills/analyze-nuve-firmware/scripts/inventory_qt6_qv4.py \
  /path/to/appStherm-1.5.8 --instruction-header /path/to/qt-6.4.0-qv4instr_moth_p.h \
  > /private/path/QV4-1.5.8-INVENTORY.private.json
.venv/bin/python scripts/build_ui_action_register.py \
  /private/path/QV4-1.5.8-INVENTORY.private.json \
  > /private/path/UI-ACTION-REGISTER-1.5.8.private.json
```

Regenerate this Markdown with `--format markdown`. Hashes and counts must match before comparison. No command in this workflow contacts a thermostat or network service.
