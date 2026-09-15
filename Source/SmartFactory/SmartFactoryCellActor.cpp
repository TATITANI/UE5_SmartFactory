#include "SmartFactoryCellActor.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "IsaacBridgeComponent.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{

TSharedPtr<FJsonObject> ChildObject(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
{
    const TSharedPtr<FJsonObject>* Child = nullptr;
    return Object.IsValid() && Object->TryGetObjectField(Key, Child) ? *Child : nullptr;
}

FVector ReadVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, const FVector& Fallback)
{
    const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
    if (!Object.IsValid() || !Object->TryGetArrayField(Key, Values) || Values->Num() != 3)
    {
        return Fallback;
    }
    FVector Result;
    for (int32 Index = 0; Index < 3; ++Index)
    {
        double Value = 0;
        if (!(*Values)[Index].IsValid() || !(*Values)[Index]->TryGetNumber(Value) ||
            !FMath::IsFinite(Value) || FMath::Abs(Value) > 1000.0)
        {
            return Fallback;
        }
        Result[Index] = Value;
    }
    return Result;
}

FString StringField(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
{
    FString Value;
    if (Object.IsValid())
    {
        Object->TryGetStringField(Key, Value);
    }
    return Value;
}
} // namespace

ASmartFactoryCellActor::ASmartFactoryCellActor()
{
    PrimaryActorTick.bCanEverTick = true;
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("FactoryRoot"));
    Bridge = CreateDefaultSubobject<UIsaacBridgeComponent>(TEXT("IsaacBridge"));
}

FVector ASmartFactoryCellActor::IsaacToUnreal(const FVector& Metres)
{
    return FVector(Metres.X * 100.0, -Metres.Y * 100.0, Metres.Z * 100.0);
}

void ASmartFactoryCellActor::BeginPlay()
{
    Super::BeginPlay();
    AddTickPrerequisiteComponent(Bridge);
    BindAuthoredComponents();
}

void ASmartFactoryCellActor::BindAuthoredComponents()
{
    Arm.Empty();
    ProductPool.Empty();
    BeltSlats.Empty();
    Signals.Init(nullptr, 3);
    Sensor = nullptr;
    TInlineComponentArray<UStaticMeshComponent*> Components(this);
    AuthoredComponentCount = Components.Num();
    for (UStaticMeshComponent* Component : Components)
    {
        for (const FName Tag : Component->ComponentTags)
        {
            const FString Name = Tag.ToString();
            if (Name.StartsWith(TEXT("Arm:")))
            {
                Arm.Add(FName(*Name.Mid(4)), Component);
            }
            else if (Name == TEXT("Sensor"))
            {
                Sensor = Component;
            }
            else if (Name == TEXT("BeltSlat"))
            {
                BeltSlats.Add(Component);
            }
            else if (Name == TEXT("Product"))
            {
                ProductPool.Add(Component);
                Component->SetVisibility(false, true);
            }
            else if (Name.StartsWith(TEXT("Signal:")))
            {
                const int32 Index = FCString::Atoi(*Name.Mid(7));
                if (Signals.IsValidIndex(Index))
                {
                    Signals[Index] = Component;
                }
            }
        }
    }
    auto ByName = [](const UStaticMeshComponent& A, const UStaticMeshComponent& B)
    {
        return A.GetName() < B.GetName();
    };
    BeltSlats.Sort(ByName);
    ProductPool.Sort(ByName);
    const TCHAR* Required[] = {
        TEXT("Housing"),  TEXT("Shoulder"),   TEXT("ShoulderCap"), TEXT("ShoulderBolt"), TEXT("Elbow"),
        TEXT("ElbowCap"), TEXT("ElbowBolt"),  TEXT("Wrist"),       TEXT("WristCap"),     TEXT("WristBolt"),
        TEXT("Upper"),    TEXT("Forearm"),    TEXT("UpperPanel"),  TEXT("ForearmPanel"), TEXT("Tool"),
        TEXT("Gripper"),  TEXT("LeftFinger"), TEXT("RightFinger")};
    bSceneReady = Sensor && BeltSlats.Num() == 26 && ProductPool.Num() > 0 && !Signals.Contains(nullptr);
    for (const TCHAR* Name : Required)
    {
        bSceneReady &= Arm.Contains(Name);
    }
    for (UStaticMeshComponent* Component : Components)
    {
        bSceneReady &= Component->GetStaticMesh() != nullptr;
    }
    RenderedProductCount = 0;
    bProductPoolOverflow = false;
    LastSequence = -1;
    if (!bSceneReady)
    {
        UE_LOG(LogTemp, Error,
               TEXT("%s: authored factory components are incomplete. Re-save BP_SmartFactoryCell."),
               *GetName());
    }
}

void ASmartFactoryCellActor::SetMaterial(UStaticMeshComponent* Component, FName Material)
{
    if (Component)
    {
        if (const auto* Found = MaterialPalette.Find(Material))
        {
            Component->SetMaterial(0, *Found);
        }
    }
}

void ASmartFactoryCellActor::Pose(UStaticMeshComponent* Component, const FVector& Position)
{
    Component->SetRelativeLocation(IsaacToUnreal(Position));
}

void ASmartFactoryCellActor::SetBeam(UStaticMeshComponent* Component, const FVector& Start,
                                     const FVector& End, double Width, double Depth)
{
    Pose(Component, (Start + End) * 0.5);
    Component->SetRelativeRotation(
        FQuat::FindBetweenNormals(FVector::UpVector, IsaacToUnreal(End - Start).GetSafeNormal()));
    const FVector Extent = Component->GetStaticMesh()->GetBoundingBox().GetSize();
    Component->SetRelativeScale3D(
        FVector(Width * 100 / Extent.X, Depth * 100 / Extent.Y, (End - Start).Size() * 100 / Extent.Z));
}

void ASmartFactoryCellActor::ReadConfiguration(const TSharedPtr<FJsonObject>& Configuration)
{
    const auto Conveyor = ChildObject(Configuration, TEXT("conveyor"));
    ConveyorStart = ReadVector(Conveyor, TEXT("start"), FVector(-1.45, 0, 0.72));
    ConveyorPickup = ReadVector(Conveyor, TEXT("pickup"), FVector(0.25, 0, 0.72));
    const auto Robot = ChildObject(Configuration, TEXT("robot"));
    RobotBase = ReadVector(Robot, TEXT("base"), FVector(0.25, 0.68, 0.72));
    RobotHome = ReadVector(Robot, TEXT("home"), FVector(0.25, 0.33, 1.25));
    ProductSize = ReadVector(ChildObject(Configuration, TEXT("product")), TEXT("size"), FVector(0.08));
    for (int32 Index = 0; Index < 3; ++Index)
    {
        ProductSize[Index] = FMath::Clamp(ProductSize[Index], 0.005, 1.0);
    }
    const auto Bins = ChildObject(Configuration, TEXT("bins"));
    RedBin = ReadVector(Bins, TEXT("red"), FVector(0.9, 0.4, 0.72));
    BlueBin = ReadVector(Bins, TEXT("blue"), FVector(0.9, 1, 0.72));
}

void ASmartFactoryCellActor::UpdateArm(const FVector& Target, bool bGripperClosed)
{
    // Isaac의 solve_arm_ik와 동일한 팔꿈치 위쪽 해석적 IK를 적용합니다.
    constexpr double UpperLength = 0.65, ForearmLength = 0.60, ToolLength = 0.15;
    const FVector Shoulder = RobotBase + FVector(0, 0, 0.33);
    FVector Offset = Target + FVector(0, 0, ToolLength) - Shoulder;
    double Radial = FMath::Sqrt(Offset.X * Offset.X + Offset.Y * Offset.Y);
    const double Distance = Offset.Size();
    const double Yaw = Radial > 1e-12 ? FMath::Atan2(Offset.Y, Offset.X) : 0.0;
    const double SolvedDistance = FMath::Clamp(Distance, FMath::Abs(UpperLength - ForearmLength) + 1e-8,
                                               UpperLength + ForearmLength - 1e-8);
    if (Distance < 1e-12)
    {
        Radial = SolvedDistance;
        Offset.Z = 0;
    }
    else
    {
        Radial *= SolvedDistance / Distance;
        Offset.Z *= SolvedDistance / Distance;
    }
    const double Cosine =
        (SolvedDistance * SolvedDistance - UpperLength * UpperLength - ForearmLength * ForearmLength) /
        (2 * UpperLength * ForearmLength);
    const double ElbowAngle = -FMath::Acos(FMath::Clamp(Cosine, -1.0, 1.0));
    const double ShoulderAngle =
        FMath::Atan2(Offset.Z, Radial) - FMath::Atan2(ForearmLength * FMath::Sin(ElbowAngle),
                                                      UpperLength + ForearmLength * FMath::Cos(ElbowAngle));
    const double C = FMath::Cos(Yaw), S = FMath::Sin(Yaw);
    const double ElbowRadial = UpperLength * FMath::Cos(ShoulderAngle);
    const FVector Elbow =
        Shoulder + FVector(ElbowRadial * C, ElbowRadial * S, UpperLength * FMath::Sin(ShoulderAngle));
    const FVector Wrist = Shoulder + FVector(Radial * C, Radial * S, Offset.Z);
    const FVector Tool = Wrist - FVector(0, 0, ToolLength);
    ToolReachErrorMeters = FVector::Distance(Tool, Target);
    ToolWorldPosition = GetActorTransform().TransformPosition(IsaacToUnreal(Tool));
    Pose(Arm[TEXT("Housing")], Shoulder - FVector(0, 0, 0.10));
    Arm[TEXT("Housing")]->SetRelativeRotation(FRotator(0, -FMath::RadiansToDegrees(Yaw), 0));
    const FVector Axis(-S, C, 0);
    const FQuat JointRotation =
        FQuat::FindBetweenNormals(FVector::UpVector, IsaacToUnreal(Axis).GetSafeNormal());
    const FName Names[] = {TEXT("Shoulder"), TEXT("Elbow"), TEXT("Wrist")};
    const FVector Points[] = {Shoulder, Elbow, Wrist};
    const double Offsets[] = {0.129, 0.104, 0.077};
    for (int32 Index = 0; Index < 3; ++Index)
    {
        auto* Joint = Arm[Names[Index]];
        auto* Cap = Arm[FName(*(Names[Index].ToString() + TEXT("Cap")))];
        auto* Bolt = Arm[FName(*(Names[Index].ToString() + TEXT("Bolt")))];
        Pose(Joint, Points[Index]);
        Pose(Cap, Points[Index] - Axis * Offsets[Index]);
        Pose(Bolt, Points[Index] - Axis * (Offsets[Index] + 0.012));
        Joint->SetRelativeRotation(JointRotation);
        Cap->SetRelativeRotation(JointRotation);
        Bolt->SetRelativeRotation(JointRotation);
    }
    SetBeam(Arm[TEXT("Upper")], Shoulder, Elbow, 0.13, 0.15);
    SetBeam(Arm[TEXT("UpperPanel")], FMath::Lerp(Shoulder, Elbow, 0.18), FMath::Lerp(Shoulder, Elbow, 0.82),
            0.07, 0.156);
    SetBeam(Arm[TEXT("Forearm")], Elbow, Wrist, 0.105, 0.115);
    SetBeam(Arm[TEXT("ForearmPanel")], FMath::Lerp(Elbow, Wrist, 0.20), FMath::Lerp(Elbow, Wrist, 0.80),
            0.045, 0.120);
    Pose(Arm[TEXT("Tool")], Tool + FVector(0, 0, 0.112));
    Pose(Arm[TEXT("Gripper")], Tool + FVector(0, 0, 0.052));
    const double Gap = ProductSize.Y * 0.5 + (bGripperClosed ? 0.017 : 0.047);
    Pose(Arm[TEXT("LeftFinger")], Tool + FVector(0, -Gap, -0.003));
    Pose(Arm[TEXT("RightFinger")], Tool + FVector(0, Gap, -0.003));
}

void ASmartFactoryCellActor::UpdateProducts(const TSharedPtr<FJsonObject>& Snapshot)
{
    TArray<TSharedPtr<FJsonObject>> VisibleProducts;
    const auto Active = ChildObject(Snapshot, TEXT("active_product"));
    if (Active.IsValid())
    {
        VisibleProducts.Add(Active);
    }
    const TArray<TSharedPtr<FJsonValue>>* Placed = nullptr;
    if (Snapshot->TryGetArrayField(TEXT("placed_products"), Placed))
    {
        for (const auto& Item : *Placed)
        {
            if (Item.IsValid() && Item->Type == EJson::Object)
            {
                VisibleProducts.Add(Item->AsObject());
            }
        }
    }

    RenderedProductCount = FMath::Min(VisibleProducts.Num(), ProductPool.Num());
    const bool bOverflow = VisibleProducts.Num() > ProductPool.Num();
    if (bOverflow && !bProductPoolOverflow)
    {
        UE_LOG(LogTemp, Error,
               TEXT("%s: %d products exceed the authored pool of %d. Increase the saved Blueprint pool."),
               *GetName(), VisibleProducts.Num(), ProductPool.Num());
    }
    bProductPoolOverflow = bOverflow;
    for (int32 Index = 0; Index < ProductPool.Num(); ++Index)
    {
        UStaticMeshComponent* Body = ProductPool[Index];
        Body->SetVisibility(Index < RenderedProductCount, true);
        if (Index >= RenderedProductCount)
        {
            continue;
        }
        const auto& Product = VisibleProducts[Index];
        SetMaterial(Body, StringField(Product, TEXT("color")) == TEXT("red") ? TEXT("Red") : TEXT("Blue"));
        Body->SetRelativeScale3D(ProductSize);
        Pose(Body, ReadVector(Product, TEXT("position"), ConveyorStart));
    }
}

void ASmartFactoryCellActor::ApplySnapshot(const TSharedPtr<FJsonObject>& Snapshot)
{
    const auto Robot = ChildObject(Snapshot, TEXT("robot_target"));
    bool bClosed = false;
    if (Robot.IsValid())
    {
        Robot->TryGetBoolField(TEXT("gripper_closed"), bClosed);
    }
    UpdateArm(ReadVector(Robot, TEXT("position"), RobotHome), bClosed);
    UpdateProducts(Snapshot);
    bool bSensorActive = false;
    Snapshot->TryGetBoolField(TEXT("pickup_sensor"), bSensorActive);
    SetMaterial(Sensor, bSensorActive ? TEXT("Green") : TEXT("Cyan"));
    const FString Mode = StringField(Snapshot, TEXT("mode"));
    SetMaterial(Signals[0], Mode == TEXT("running") ? TEXT("Green") : TEXT("Black"));
    SetMaterial(Signals[1], Mode != TEXT("running") && Mode != TEXT("emergency_stopped") ? TEXT("Yellow")
                                                                                         : TEXT("Black"));
    SetMaterial(Signals[2], Mode == TEXT("emergency_stopped") ? TEXT("Red") : TEXT("Black"));

    // 공정 상태에서 벨트 이동량을 계산하여 정지 또는 수신 지연 중 위치가 흐르지 않게 합니다.
    const double TravelLength = FVector::Distance(ConveyorStart, ConveyorPickup);
    const double RenderLength = FMath::Max(0.4, FMath::Abs(ConveyorPickup.X - ConveyorStart.X) + 0.46);
    const double StartX = (ConveyorStart.X + ConveyorPickup.X - RenderLength) * 0.5;
    const auto Active = ChildObject(Snapshot, TEXT("active_product"));
    double Progress = TravelLength;
    if (Active.IsValid() && StringField(Snapshot, TEXT("state")) == TEXT("conveying"))
    {
        const FVector Position = ReadVector(Active, TEXT("position"), ConveyorStart);
        Progress = FMath::Min(TravelLength,
                              FVector2D(Position.X - ConveyorStart.X, Position.Y - ConveyorStart.Y).Size());
    }
    double Spawned = 0;
    if (const auto Counters = ChildObject(Snapshot, TEXT("counters")))
    {
        Counters->TryGetNumberField(TEXT("spawned"), Spawned);
    }
    const double BeltOffset = FMath::Max(0.0, Spawned - 1) * TravelLength + Progress;
    for (int32 Index = 0; Index < BeltSlats.Num(); ++Index)
    {
        Pose(BeltSlats[Index],
             FVector(StartX + FMath::Fmod(Index * RenderLength / BeltSlats.Num() + BeltOffset, RenderLength),
                     ConveyorStart.Y, ConveyorStart.Z + 0.002));
    }
}

void ASmartFactoryCellActor::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (!Bridge || !Bridge->bHasFreshState || !Bridge->GetSnapshot().IsValid())
    {
        return;
    }
    if (LastSequence == Bridge->SnapshotSequence && LastSession == Bridge->SessionId)
    {
        return;
    }
    const bool bSessionChanged = LastSession != Bridge->SessionId;
    const auto& Configuration = Bridge->GetConfiguration();
    FString Serialized;
    if (Configuration.IsValid())
    {
        FJsonSerializer::Serialize(Configuration.ToSharedRef(), TJsonWriterFactory<>::Create(&Serialized));
    }
    if (bSessionChanged || Serialized != LastConfiguration)
    {
        ReadConfiguration(Configuration);
        // 재접속이나 설정 변경 중에도 저장된 컴포넌트 구성을 유지합니다.
        LastConfiguration = Serialized;
    }
    if (bSceneReady)
    {
        ApplySnapshot(Bridge->GetSnapshot());
    }
    LastSequence = Bridge->SnapshotSequence;
    LastSession = Bridge->SessionId;
}
