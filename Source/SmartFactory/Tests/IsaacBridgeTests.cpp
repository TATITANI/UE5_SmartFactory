#if WITH_DEV_AUTOMATION_TESTS

#include "../IsaacBridgeComponent.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#include <limits>

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FIsaacBridgeProtocolTest, "SmartFactory.IsaacBridge.ProtocolResilience",
                                 EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FIsaacBridgeProtocolTest::RunTest(const FString& Parameters)
{
    // 실제 프로토콜 입력으로 장면 코드가 JSON을 소비하기 전에 경계를 검증합니다.
    const FString Valid = TEXT(
        R"JSON({"type":"snapshot","protocol":1,"session_id":"server-a","sequence":42,"config":{},"snapshot":{"simulation_time":1.25,"mode":"running","state":"conveying","conveyor_running":true,"pickup_sensor":false,"robot_target":{"position":[0.25,0.33,1.25],"gripper_closed":false},"active_product":{"id":1,"color":"red","position":[-1,0,0.76],"attached":false},"placed_products":[],"counters":{"placed":0,"by_color":{"red":0,"blue":0}},"robot_joint_state":{"names":["base"],"positions":[0],"reach_error":0,"reachable":true}}})JSON");
    UIsaacBridgeComponent* Bridge = NewObject<UIsaacBridgeComponent>();
    Bridge->bConnected = true;
    const double Now = FPlatformTime::Seconds();
    TestTrue(TEXT("Accept valid simulator state"), Bridge->ProcessFrame(Valid, Now));
    TestEqual(TEXT("Expose simulator sequence"), Bridge->SnapshotSequence, static_cast<int64>(42));
    TestTrue(TEXT("Connected valid state is fresh"), Bridge->bHasFreshState);
    TestEqual(TEXT("Expose simulator time"), Bridge->SimulationTime, 1.25);

    const double ReceivedAt = Bridge->LastSnapshotAt;
    TestTrue(TEXT("Duplicate sequence is harmless"), Bridge->ProcessFrame(Valid, Now + 1.0));
    TestEqual(TEXT("Duplicate must not refresh watchdog"), Bridge->LastSnapshotAt, ReceivedAt);
    TestTrue(
        TEXT("Old sequence is harmless"),
        Bridge->ProcessFrame(Valid.Replace(TEXT("\"sequence\":42"), TEXT("\"sequence\":41")), Now + 1.1));
    TestEqual(TEXT("Old sequence does not rewind"), Bridge->SnapshotSequence, static_cast<int64>(42));

    const TArray<FString> Malformed = {
        TEXT("{}"),
        TEXT("[]"),
        TEXT("{broken"),
        Valid.Replace(TEXT("\"protocol\":1"), TEXT("\"protocol\":2")),
        Valid.Replace(TEXT("\"sequence\":42"), TEXT("\"sequence\":-1")),
        Valid.Replace(TEXT("\"sequence\":42"), TEXT("\"sequence\":42.5")),
        Valid.Replace(TEXT("\"sequence\":42"), TEXT("\"sequence\":\"42\"")),
        Valid.Replace(TEXT("\"position\":[0.25,0.33,1.25]"), TEXT("\"position\":[0.25,0.33]")),
        Valid.Replace(TEXT("\"position\":[-1,0,0.76]"), TEXT("\"position\":[1e100,0,0.76]")),
        Valid.Replace(TEXT("\"attached\":false"), TEXT("\"attached\":\"false\"")),
        Valid.Replace(TEXT("\"placed\":0"), TEXT("\"placed\":1")),
        Valid.Replace(TEXT("\"positions\":[0]"), TEXT("\"positions\":[]")),
        Valid.Replace(TEXT("\"state\":\"conveying\""), TEXT("\"state\":null"))};
    for (int32 Index = 0; Index < Malformed.Num(); ++Index)
    {
        TestFalse(FString::Printf(TEXT("Reject malformed fixture %d"), Index),
                  Bridge->ProcessFrame(Malformed[Index], Now + 1.2));
        TestEqual(TEXT("Rejected frame must not refresh watchdog"), Bridge->LastSnapshotAt, ReceivedAt);
        TestEqual(TEXT("Rejected frame preserves valid sequence"), Bridge->SnapshotSequence,
                  static_cast<int64>(42));
    }

    Bridge->PendingCommands.Add(TEXT("old-command"),
                                UIsaacBridgeComponent::FPendingCommand{TEXT("resume"), Now});
    Bridge->LastCommandId = TEXT("old-command");
    const FString Restart = Valid.Replace(TEXT("server-a"), TEXT("server-b"))
                                .Replace(TEXT("\"sequence\":42"), TEXT("\"sequence\":0"));
    TestTrue(TEXT("New server session may restart sequence"), Bridge->ProcessFrame(Restart, Now + 1.3));
    TestEqual(TEXT("Server session reset sequence"), Bridge->SnapshotSequence, static_cast<int64>(0));
    TestTrue(TEXT("Server restart invalidates old pending controls"), Bridge->PendingCommands.IsEmpty());

    const FString Ack = TEXT(
        R"JSON({"type":"ack","protocol":1,"id":"current-command","command":"pause","accepted":true,"mode":"paused","reason":""})JSON");
    Bridge->PendingCommands.Add(TEXT("current-command"),
                                UIsaacBridgeComponent::FPendingCommand{TEXT("pause"), Now});
    Bridge->LastCommandId = TEXT("current-command");
    TestTrue(TEXT("Unknown acknowledgement is harmless"),
             Bridge->ProcessFrame(Ack.Replace(TEXT("current-command"), TEXT("unknown-command")), Now + 1.4));
    TestFalse(TEXT("Unknown acknowledgement cannot accept current command"), Bridge->bLastCommandAccepted);
    TestEqual(TEXT("Unknown acknowledgement keeps pending command"), Bridge->PendingCommands.Num(), 1);
    TestTrue(TEXT("Accept matching acknowledgement"), Bridge->ProcessFrame(Ack, Now + 1.5));
    TestTrue(TEXT("Matching acknowledgement completes command"),
             Bridge->bLastCommandAccepted && Bridge->PendingCommands.IsEmpty());
    TestEqual(TEXT("Acknowledgement does not replace authoritative snapshot mode"), Bridge->Mode,
              FString(TEXT("running")));

    // 속도 제어는 인자 없는 네 가지 제어와 구분되는 숫자 명령입니다.
    // 실제로 직렬화한 전송 데이터를 검사합니다.
    FString SpeedId, SpeedFrame;
    TestTrue(TEXT("Encode speed command"),
             UIsaacBridgeComponent::EncodeCommand(TEXT("set_conveyor_speed"), TOptional<double>(0.55),
                                                  SpeedId, SpeedFrame));
    TestTrue(TEXT("Speed frame is newline terminated"), SpeedFrame.EndsWith(TEXT("\n")));
    TSharedPtr<FJsonObject> EncodedSpeed;
    const bool bDecodedSpeed =
        FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(SpeedFrame), EncodedSpeed);
    TestTrue(TEXT("Speed frame is valid JSON"), bDecodedSpeed && EncodedSpeed.IsValid());
    if (bDecodedSpeed && EncodedSpeed.IsValid())
    {
        TestEqual(TEXT("Speed wire command"), EncodedSpeed->GetStringField(TEXT("command")),
                  FString(TEXT("set_conveyor_speed")));
        TestEqual(TEXT("Speed wire ID is correlated"), EncodedSpeed->GetStringField(TEXT("id")), SpeedId);
        TestTrue(TEXT("Speed wire value stays numeric"),
                 EncodedSpeed->HasTypedField<EJson::Number>(TEXT("value")));
        TestEqual(TEXT("Speed wire value"), EncodedSpeed->GetNumberField(TEXT("value")), 0.55);
        TestEqual(TEXT("Speed uses protocol one"), EncodedSpeed->GetNumberField(TEXT("protocol")), 1.0);
    }
    for (double Boundary : {0.05, 1.0})
    {
        TestTrue(TEXT("Inclusive speed boundary is accepted"),
                 UIsaacBridgeComponent::EncodeCommand(TEXT("set_conveyor_speed"), TOptional<double>(Boundary),
                                                      SpeedId, SpeedFrame));
    }
    for (double InvalidSpeed : {0.0, 0.049, 1.01, -1.0, std::numeric_limits<double>::quiet_NaN(),
                                std::numeric_limits<double>::infinity()})
    {
        TestFalse(TEXT("Invalid speed cannot enter wire queue"),
                  UIsaacBridgeComponent::EncodeCommand(TEXT("set_conveyor_speed"),
                                                       TOptional<double>(InvalidSpeed), SpeedId, SpeedFrame));
        TestTrue(TEXT("Invalid speed leaves no encoded command"), SpeedId.IsEmpty() && SpeedFrame.IsEmpty());
    }
    TestFalse(TEXT("Speed command requires a value"),
              UIsaacBridgeComponent::EncodeCommand(TEXT("set_conveyor_speed"), TOptional<double>(), SpeedId,
                                                   SpeedFrame));
    TestFalse(
        TEXT("Parameterless commands cannot carry speed"),
        UIsaacBridgeComponent::EncodeCommand(TEXT("resume"), TOptional<double>(0.55), SpeedId, SpeedFrame));
    TestFalse(TEXT("Simple public API cannot send valueless speed control"),
              Bridge->SendCommand(TEXT("set_conveyor_speed")));

    UIsaacBridgeComponent* SpeedBridge = NewObject<UIsaacBridgeComponent>();
    SpeedBridge->bConnected = true;
    const FString LegacySpeedSnapshot =
        Valid.Replace(TEXT("\"config\":{}"), TEXT("\"config\":{\"conveyor\":{\"speed\":0.25}}"));
    TestTrue(TEXT("Legacy snapshot uses configuration speed"),
             SpeedBridge->ProcessFrame(LegacySpeedSnapshot, Now));
    TestEqual(TEXT("Legacy conveyor setpoint"), SpeedBridge->ConveyorSpeedSetpoint, 0.25);
    TestEqual(TEXT("Missing effective speed defaults to stopped"), SpeedBridge->EffectiveConveyorSpeed, 0.0);
    const FString SpeedSnapshot =
        LegacySpeedSnapshot.Replace(TEXT("\"sequence\":42"), TEXT("\"sequence\":43"))
            .Replace(TEXT("\"simulation_time\":1.25"),
                     TEXT("\"simulation_time\":1.25,\"conveyor_speed_setpoint\":0.55,\"conveyor_speed\":0.0"))
            .Replace(TEXT("\"mode\":\"running\""), TEXT("\"mode\":\"paused\""))
            .Replace(TEXT("\"conveyor_running\":true"), TEXT("\"conveyor_running\":false"));
    TestTrue(TEXT("Paused speed snapshot is accepted"), SpeedBridge->ProcessFrame(SpeedSnapshot, Now + 0.1));
    TestEqual(TEXT("Explicit setpoint overrides legacy configuration"), SpeedBridge->ConveyorSpeedSetpoint,
              0.55);
    TestEqual(TEXT("Paused belt effective speed remains zero"), SpeedBridge->EffectiveConveyorSpeed, 0.0);
    const double SpeedReceivedAt = SpeedBridge->LastSnapshotAt;
    const TArray<FString> MalformedSpeedSnapshots = {
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed_setpoint\":0.55"),
                              TEXT("\"conveyor_speed_setpoint\":0.0")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed_setpoint\":0.55"),
                              TEXT("\"conveyor_speed_setpoint\":1.01")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed_setpoint\":0.55"),
                              TEXT("\"conveyor_speed_setpoint\":\"0.55\"")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed_setpoint\":0.55"),
                              TEXT("\"conveyor_speed_setpoint\":true")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed_setpoint\":0.55"),
                              TEXT("\"conveyor_speed_setpoint\":NaN")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed_setpoint\":0.55"),
                              TEXT("\"conveyor_speed_setpoint\":1e999")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed\":0.0"), TEXT("\"conveyor_speed\":-0.1")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed\":0.0"), TEXT("\"conveyor_speed\":1.1")),
        SpeedSnapshot.Replace(TEXT("\"conveyor_speed\":0.0"), TEXT("\"conveyor_speed\":NaN")),
        LegacySpeedSnapshot.Replace(TEXT("\"speed\":0.25"), TEXT("\"speed\":\"0.25\""))};
    for (const FString& InvalidSnapshot : MalformedSpeedSnapshots)
    {
        TestFalse(TEXT("Malformed speed snapshot is rejected"),
                  SpeedBridge->ProcessFrame(InvalidSnapshot, Now + 0.2));
        TestEqual(TEXT("Bad speed leaves last valid setpoint intact"), SpeedBridge->ConveyorSpeedSetpoint,
                  0.55);
        TestEqual(TEXT("Bad speed does not refresh state watchdog"), SpeedBridge->LastSnapshotAt,
                  SpeedReceivedAt);
    }
    const FString SpeedAck = TEXT(
        R"JSON({"type":"ack","protocol":1,"id":"speed-command","command":"set_conveyor_speed","accepted":true,"mode":"paused","reason":""})JSON");
    SpeedBridge->PendingCommands.Add(
        TEXT("speed-command"),
        UIsaacBridgeComponent::FPendingCommand{TEXT("set_conveyor_speed"), Now, TOptional<double>(0.60)});
    SpeedBridge->LastCommandId = TEXT("speed-command");
    TestFalse(
        TEXT("ACK cannot change requested speed"),
        SpeedBridge->ProcessFrame(
            SpeedAck.Replace(TEXT("\"reason\":\"\""), TEXT("\"reason\":\"\",\"value\":0.70")), Now + 0.3));
    TestFalse(
        TEXT("ACK cannot contain nonfinite speed"),
        SpeedBridge->ProcessFrame(
            SpeedAck.Replace(TEXT("\"reason\":\"\""), TEXT("\"reason\":\"\",\"value\":NaN")), Now + 0.3));
    TestTrue(TEXT("Speed ACK without optional value is accepted"),
             SpeedBridge->ProcessFrame(SpeedAck, Now + 0.4));
    TestTrue(TEXT("Speed acknowledgement completes matching command"),
             SpeedBridge->bLastCommandAccepted && SpeedBridge->PendingCommands.IsEmpty());
    TestEqual(TEXT("Speed ACK does not invent authoritative setpoint"), SpeedBridge->ConveyorSpeedSetpoint,
              0.55);
    SpeedBridge->PendingCommands.Add(
        TEXT("speed-command-2"),
        UIsaacBridgeComponent::FPendingCommand{TEXT("set_conveyor_speed"), Now, TOptional<double>(0.65)});
    SpeedBridge->LastCommandId = TEXT("speed-command-2");
    TestTrue(TEXT("Matching optional speed echo is accepted"),
             SpeedBridge->ProcessFrame(
                 SpeedAck.Replace(TEXT("speed-command"), TEXT("speed-command-2"))
                     .Replace(TEXT("\"reason\":\"\""), TEXT("\"reason\":\"\",\"value\":0.65")),
                 Now + 0.5));
    const FString MovingSnapshot =
        SpeedSnapshot.Replace(TEXT("\"sequence\":43"), TEXT("\"sequence\":44"))
            .Replace(TEXT("\"conveyor_speed_setpoint\":0.55"), TEXT("\"conveyor_speed_setpoint\":0.65"))
            .Replace(TEXT("\"conveyor_speed\":0.0"), TEXT("\"conveyor_speed\":0.65"))
            .Replace(TEXT("\"mode\":\"paused\""), TEXT("\"mode\":\"running\""))
            .Replace(TEXT("\"conveyor_running\":false"), TEXT("\"conveyor_running\":true"));
    TestTrue(TEXT("Moving conveyor snapshot is accepted"),
             SpeedBridge->ProcessFrame(MovingSnapshot, Now + 0.6));
    TestEqual(TEXT("Effective conveyor speed comes from live snapshot"), SpeedBridge->EffectiveConveyorSpeed,
              0.65);
    TestEqual(TEXT("Authoritative setpoint catches up after ACK"), SpeedBridge->ConveyorSpeedSetpoint, 0.65);
    TestFalse(TEXT("Speed cannot transmit without a live socket"), SpeedBridge->SendConveyorSpeed(0.65));

    TestFalse(TEXT("No socket means no control transmission"), Bridge->SendCommand(TEXT("resume")));
    Bridge->PendingCommands.Add(TEXT("unacknowledged"),
                                UIsaacBridgeComponent::FPendingCommand{TEXT("resume"), Now});
    Bridge->SendBuffer = {1, 2, 3};
    Bridge->Disconnect(TEXT("test connection closed"), Now + 2.0);
    TestFalse(TEXT("Disconnect invalidates UI freshness"), Bridge->bHasFreshState);
    TestTrue(TEXT("Disconnected control must never be replayed"),
             Bridge->SendBuffer.IsEmpty() && Bridge->PendingCommands.IsEmpty());
    return true;
}

#endif
