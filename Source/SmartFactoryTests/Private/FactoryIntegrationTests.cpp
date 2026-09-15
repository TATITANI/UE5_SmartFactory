#if WITH_DEV_AUTOMATION_TESTS

#include "Algo/AllOf.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "HAL/FileManager.h"
#include "IsaacBridgeComponent.h"
#include "Misc/AutomationTest.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "SmartFactoryCellActor.h"
#include "SmartFactoryPlayerController.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"

namespace FactoryIntegration
{
struct FStepResult
{
    bool bComplete = false;
    FString Error;

    static FStepResult Pending()
    {
        return {};
    }

    static FStepResult Passed()
    {
        return {true, {}};
    }

    static FStepResult Failed(FString Message)
    {
        return {true, MoveTemp(Message)};
    }
};

TArray<ASmartFactoryCellActor*> FindCells()
{
    UWorld* World = AutomationCommon::GetAnyGameWorld();
    if (!World)
    {
        return {};
    }
    if (auto* Controller = Cast<ASmartFactoryPlayerController>(World->GetFirstPlayerController()))
    {
        return Controller->GetFactoryCells();
    }
    return {};
}

ASmartFactoryPlayerController* FindController()
{
    UWorld* World = AutomationCommon::GetAnyGameWorld();
    return World ? Cast<ASmartFactoryPlayerController>(World->GetFirstPlayerController()) : nullptr;
}

bool IsAcknowledged(const UIsaacBridgeComponent* Bridge, bool bAccepted = true)
{
    return Bridge && !Bridge->LastCommandId.IsEmpty() &&
           Bridge->LastAcknowledgedCommandId == Bridge->LastCommandId &&
           Bridge->bLastCommandAccepted == bAccepted;
}

bool AreAllAcknowledged(const TArray<ASmartFactoryCellActor*>& Cells, bool bAccepted = true)
{
    return Algo::AllOf(Cells,
                       [bAccepted](const ASmartFactoryCellActor* Cell)
                       {
                           return Cell && IsAcknowledged(Cell->GetBridge(), bAccepted);
                       });
}

bool AreAllInMode(const TArray<ASmartFactoryCellActor*>& Cells, const FString& Mode)
{
    return Algo::AllOf(Cells,
                       [&Mode](const ASmartFactoryCellActor* Cell)
                       {
                           return Cell && Cell->GetBridge() && Cell->GetBridge()->Mode == Mode;
                       });
}

FString SendAll(const FString& Command)
{
    const TArray<ASmartFactoryCellActor*> Cells = FindCells();
    if (Cells.IsEmpty())
    {
        return TEXT("No factory cells are available.");
    }
    for (ASmartFactoryCellActor* Cell : Cells)
    {
        if (!Cell || !Cell->GetBridge() || !Cell->GetBridge()->SendCommand(Command))
        {
            return TEXT("Unable to queue command for every cell: ") + Command;
        }
    }
    return {};
}

FString VerifyToolTransform(const ASmartFactoryCellActor* Cell)
{
    if (!Cell || !Cell->bSceneReady || !Cell->GetBridge() || !Cell->GetBridge()->GetSnapshot().IsValid())
    {
        return TEXT("Factory cell scene or snapshot is unavailable.");
    }
    const TSharedPtr<FJsonObject>* Robot = nullptr;
    if (!Cell->GetBridge()->GetSnapshot()->TryGetObjectField(TEXT("robot_target"), Robot) || !Robot ||
        !Robot->IsValid())
    {
        return TEXT("Snapshot has no robot target.");
    }
    const TArray<TSharedPtr<FJsonValue>>* Position = nullptr;
    if (!(*Robot)->TryGetArrayField(TEXT("position"), Position) || !Position || Position->Num() != 3)
    {
        return TEXT("Robot target position is invalid.");
    }
    FVector IsaacTarget;
    for (int32 Index = 0; Index < 3; ++Index)
    {
        double Value = 0;
        if (!(*Position)[Index].IsValid() || !(*Position)[Index]->TryGetNumber(Value) ||
            !FMath::IsFinite(Value))
        {
            return TEXT("Robot target position contains an invalid value.");
        }
        IsaacTarget[Index] = Value;
    }
    const FVector Expected =
        Cell->GetActorTransform().TransformPosition(ASmartFactoryCellActor::IsaacToUnreal(IsaacTarget));
    return FVector::Dist(Expected, Cell->ToolWorldPosition) <= 0.001
               ? FString()
               : TEXT("Unreal tool position did not match Isaac coordinates.");
}

struct FScenarioContext : TSharedFromThis<FScenarioContext>
{
    FScenarioContext(FAutomationTestBase& InTest, bool bInHall)
        : Test(InTest), bHall(bInHall), bCapture(FParse::Param(FCommandLine::Get(), TEXT("FactoryCapture")))
    {
        ScreenshotPath = FPaths::ConvertRelativePathToFull(
            FPaths::ProjectSavedDir() /
            (bHall ? TEXT("Tests/FactoryHall.png") : TEXT("Tests/UnrealFactory.png")));
        ReportPath = FPaths::ProjectSavedDir() / (bHall ? TEXT("Tests/FactoryHallIntegration.json")
                                                        : TEXT("Tests/FactoryBridgeIntegration.json"));
        IFileManager::Get().Delete(*ReportPath);
        if (bCapture)
        {
            IFileManager::Get().Delete(*ScreenshotPath);
        }
    }

    bool WriteReport(bool bSuccess, const FString& Detail) const
    {
        TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
        Report->SetBoolField(TEXT("success"), bSuccess);
        Report->SetStringField(TEXT("detail"), Detail);
        Report->SetBoolField(TEXT("ros2_enabled"), false);
        Report->SetStringField(TEXT("transport"), TEXT("loopback TCP JSONL protocol 1"));

        TArray<TSharedPtr<FJsonValue>> Values;
        for (const FString& Check : Checks)
        {
            Values.Add(MakeShared<FJsonValueString>(Check));
        }
        Report->SetArrayField(TEXT("checks"), MoveTemp(Values));

        const TArray<ASmartFactoryCellActor*> Cells = FindCells();
        if (bHall)
        {
            TArray<TSharedPtr<FJsonValue>> CellReports;
            for (const ASmartFactoryCellActor* Cell : Cells)
            {
                const UIsaacBridgeComponent* Bridge = Cell->GetBridge();
                TSharedRef<FJsonObject> CellReport = MakeShared<FJsonObject>();
                CellReport->SetNumberField(TEXT("port"), Bridge->Port);
                CellReport->SetNumberField(TEXT("sorted"), Bridge->SortedCount);
                CellReport->SetNumberField(TEXT("speed"), Bridge->ConveyorSpeedSetpoint);
                CellReport->SetStringField(TEXT("mode"), Bridge->Mode);
                CellReport->SetNumberField(TEXT("authored_components"), Cell->AuthoredComponentCount);
                CellReport->SetBoolField(TEXT("product_pool_overflow"), Cell->bProductPoolOverflow);
                CellReports.Add(MakeShared<FJsonValueObject>(CellReport));
            }
            Report->SetArrayField(TEXT("cells"), MoveTemp(CellReports));
        }
        if (!Cells.IsEmpty() && Cells[0] && Cells[0]->GetBridge())
        {
            const UIsaacBridgeComponent* Bridge = Cells[0]->GetBridge();
            Report->SetStringField(TEXT("session_id"), Bridge->SessionId);
            Report->SetNumberField(TEXT("sequence"), static_cast<double>(Bridge->SnapshotSequence));
            Report->SetNumberField(TEXT("sorted"), Bridge->SortedCount);
            Report->SetNumberField(TEXT("rendered_products"), Cells[0]->RenderedProductCount);
            Report->SetStringField(TEXT("last_command"), Bridge->LastCommandStatus);
        }

        FString Output;
        FJsonSerializer::Serialize(Report, TJsonWriterFactory<>::Create(&Output));
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(ReportPath), true);
        return FFileHelper::SaveStringToFile(Output, *ReportPath);
    }

    FAutomationTestBase& Test;
    const bool bHall;
    const bool bCapture;
    FString ScreenshotPath;
    FString ReportPath;
    TArray<FString> Checks;
    TArray<double> FrozenTimes;
    double FrozenSimulationTime = 0;
    double PhaseStartedAt = 0;
};

class FScenarioStepCommand final : public IAutomationLatentCommand
{
public:
    using FBegin = TFunction<FString()>;
    using FPoll = TFunction<FStepResult()>;

    FScenarioStepCommand(TSharedRef<FScenarioContext> InContext, FString InName, double InTimeout,
                         FBegin InBegin, FPoll InPoll, FString InCheck)
        : Context(MoveTemp(InContext)), Name(MoveTemp(InName)), Timeout(InTimeout), Begin(MoveTemp(InBegin)),
          Poll(MoveTemp(InPoll)), Check(MoveTemp(InCheck))
    {
    }

    virtual bool Update() override
    {
        if (!bStarted)
        {
            bStarted = true;
            if (Begin)
            {
                const FString Error = Begin();
                if (!Error.IsEmpty())
                {
                    return Fail(Error);
                }
            }
        }

        const FStepResult Result = Poll ? Poll() : FStepResult::Passed();
        if (!Result.bComplete)
        {
            return GetCurrentRunTime() >= Timeout
                       ? Fail(FString::Printf(TEXT("Timed out after %.1f seconds."), Timeout))
                       : false;
        }
        if (!Result.Error.IsEmpty())
        {
            return Fail(Result.Error);
        }
        if (!Check.IsEmpty())
        {
            Context->Checks.Add(Check);
        }
        Context->Test.AddInfo(Name);
        return true;
    }

private:
    bool Fail(const FString& Error)
    {
        const FString Detail = Name + TEXT(": ") + Error;
        Context->WriteReport(false, Detail);
        FAutomationTestFramework::Get().DequeueAllCommands();
        Context->Test.AddError(Detail);
        UE_LOG(LogTemp, Error, TEXT("FACTORY_INTEGRATION_FAIL: %s"), *Detail);
        return true;
    }

    TSharedRef<FScenarioContext> Context;
    FString Name;
    double Timeout;
    FBegin Begin;
    FPoll Poll;
    FString Check;
    bool bStarted = false;
};

class FScenario
{
public:
    explicit FScenario(TSharedRef<FScenarioContext> InContext) : Context(MoveTemp(InContext))
    {
    }

    FScenario& Step(FString Name, double Timeout, FScenarioStepCommand::FBegin Begin,
                    FScenarioStepCommand::FPoll Poll, FString Check = {})
    {
        ADD_LATENT_AUTOMATION_COMMAND(FScenarioStepCommand(Context, MoveTemp(Name), Timeout, MoveTemp(Begin),
                                                           MoveTemp(Poll), MoveTemp(Check)));
        return *this;
    }

    FScenario& Wait(FString Name, double Timeout, FScenarioStepCommand::FPoll Poll, FString Check = {})
    {
        return Step(MoveTemp(Name), Timeout, {}, MoveTemp(Poll), MoveTemp(Check));
    }

    FScenario& Finish(FString Detail)
    {
        return Step(TEXT("Write integration report"), 1.0, {},
                    [Context = Context, Detail = MoveTemp(Detail)]
                    {
                        if (!Context->WriteReport(true, Detail))
                        {
                            return FStepResult::Failed(TEXT("Unable to write integration report."));
                        }
                        UE_LOG(LogTemp, Display, TEXT("FACTORY_INTEGRATION_PASS: %s"), *Detail);
                        return FStepResult::Passed();
                    });
    }

private:
    TSharedRef<FScenarioContext> Context;
};

FString SendSingle(const FString& Command)
{
    const TArray<ASmartFactoryCellActor*> Cells = FindCells();
    return !Cells.IsEmpty() && Cells[0] && Cells[0]->GetBridge() &&
                   Cells[0]->GetBridge()->SendCommand(Command)
               ? FString()
               : TEXT("Unable to queue command: ") + Command;
}

FStepResult WaitForSingleCommand(bool bAccepted,
                                 const TFunction<bool(const ASmartFactoryCellActor&)>& Condition)
{
    const TArray<ASmartFactoryCellActor*> Cells = FindCells();
    if (Cells.IsEmpty() || !Cells[0] || !Cells[0]->GetBridge())
    {
        return FStepResult::Failed(TEXT("Factory cell disappeared while waiting for acknowledgement."));
    }
    const UIsaacBridgeComponent* Bridge = Cells[0]->GetBridge();
    if (Bridge->LastAcknowledgedCommandId != Bridge->LastCommandId || Bridge->LastCommandId.IsEmpty())
    {
        return FStepResult::Pending();
    }
    if (Bridge->bLastCommandAccepted != bAccepted)
    {
        return FStepResult::Failed(bAccepted ? TEXT("Isaac rejected the command.")
                                             : TEXT("Isaac unexpectedly accepted the command."));
    }
    return Condition(*Cells[0]) ? FStepResult::Passed() : FStepResult::Pending();
}

void EnqueueBridgeScenario(FAutomationTestBase& Test)
{
    const TSharedRef<FScenarioContext> Context = MakeShared<FScenarioContext>(Test, false);
    FScenario Scenario(Context);

    Scenario
        .Wait(
            TEXT("Wait for live Isaac snapshot"), 20.0,
            []
            {
                const TArray<ASmartFactoryCellActor*> Cells = FindCells();
                return !Cells.IsEmpty() && Cells[0] && Cells[0]->GetBridge() &&
                               Cells[0]->GetBridge()->bHasFreshState
                           ? FStepResult::Passed()
                           : FStepResult::Pending();
            },
            TEXT("Unreal received live Isaac snapshot"))
        .Step(
            TEXT("Reset cell"), 10.0,
            []
            {
                return SendSingle(TEXT("reset"));
            },
            []
            {
                return WaitForSingleCommand(true,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("paused") &&
                                                       Cell.GetBridge()->SortedCount == 0;
                                            });
            },
            TEXT("Unreal reset command acknowledged by Isaac"))
        .Step(
            TEXT("Resume cell"), 20.0,
            []
            {
                return SendSingle(TEXT("resume"));
            },
            []
            {
                return WaitForSingleCommand(true,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("running") &&
                                                       Cell.GetBridge()->SimulationTime > 0.4;
                                            });
            },
            TEXT("Unreal resume advances Isaac clock"))
        .Step(
            TEXT("Pause cell"), 10.0,
            []
            {
                return SendSingle(TEXT("pause"));
            },
            [Context]
            {
                FStepResult Result = WaitForSingleCommand(true,
                                                          [](const ASmartFactoryCellActor& Cell)
                                                          {
                                                              return Cell.GetBridge()->Mode == TEXT("paused");
                                                          });
                if (Result.bComplete && Result.Error.IsEmpty())
                {
                    Context->FrozenSimulationTime = FindCells()[0]->GetBridge()->SimulationTime;
                }
                return Result;
            })
        .Step(
            TEXT("Verify paused clock"), 2.0,
            [Context]
            {
                Context->PhaseStartedAt = FPlatformTime::Seconds();
                return FString();
            },
            [Context]
            {
                if (FPlatformTime::Seconds() - Context->PhaseStartedAt < 0.5)
                {
                    return FStepResult::Pending();
                }
                const TArray<ASmartFactoryCellActor*> Cells = FindCells();
                return !Cells.IsEmpty() && FMath::IsNearlyEqual(Cells[0]->GetBridge()->SimulationTime,
                                                                Context->FrozenSimulationTime, 1e-6)
                           ? FStepResult::Passed()
                           : FStepResult::Failed(TEXT("Simulation moved while paused."));
            },
            TEXT("Pause freezes Isaac simulation time"))
        .Step(
            TEXT("Emergency-stop cell"), 10.0,
            []
            {
                return SendSingle(TEXT("emergency_stop"));
            },
            []
            {
                return WaitForSingleCommand(true,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("emergency_stopped");
                                            });
            })
        .Step(
            TEXT("Reject resume while emergency-stopped"), 10.0,
            []
            {
                return SendSingle(TEXT("resume"));
            },
            []
            {
                return WaitForSingleCommand(false,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("emergency_stopped");
                                            });
            },
            TEXT("Emergency stop remains latched against resume"))
        .Step(
            TEXT("Reset emergency latch"), 10.0,
            []
            {
                return SendSingle(TEXT("reset"));
            },
            []
            {
                return WaitForSingleCommand(true,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("paused") &&
                                                       Cell.GetBridge()->SortedCount == 0;
                                            });
            },
            TEXT("Reset clears emergency latch"))
        .Step(
            TEXT("Resume sorting"), 10.0,
            []
            {
                return SendSingle(TEXT("resume"));
            },
            []
            {
                return WaitForSingleCommand(true,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("running");
                                            });
            })
        .Wait(
            TEXT("Wait for two rendered products"), 60.0,
            []
            {
                const TArray<ASmartFactoryCellActor*> Cells = FindCells();
                return !Cells.IsEmpty() && Cells[0]->GetBridge()->SortedCount >= 2 &&
                               Cells[0]->RenderedProductCount >= 2
                           ? FStepResult::Passed()
                           : FStepResult::Pending();
            },
            TEXT("Isaac sorted two products and Unreal rendered received product states"))
        .Step(
            TEXT("Pause before transform verification"), 10.0,
            []
            {
                return SendSingle(TEXT("pause"));
            },
            []
            {
                return WaitForSingleCommand(true,
                                            [](const ASmartFactoryCellActor& Cell)
                                            {
                                                return Cell.GetBridge()->Mode == TEXT("paused");
                                            });
            })
        .Step(
            TEXT("Verify rendered tool transform"), 2.0,
            [Context]
            {
                Context->PhaseStartedAt = FPlatformTime::Seconds();
                return FString();
            },
            [Context]
            {
                if (FPlatformTime::Seconds() - Context->PhaseStartedAt < 0.5)
                {
                    return FStepResult::Pending();
                }
                const TArray<ASmartFactoryCellActor*> Cells = FindCells();
                if (Cells.IsEmpty())
                {
                    return FStepResult::Failed(TEXT("Factory cell is unavailable."));
                }
                const FString Error = VerifyToolTransform(Cells[0]);
                return Error.IsEmpty() ? FStepResult::Passed() : FStepResult::Failed(Error);
            },
            TEXT("Metre/centimetre and handedness conversion matches tool position within 0.001cm"))
        .Step(
            TEXT("Capture factory screenshot"), 5.0,
            [Context]
            {
                if (Context->bCapture)
                {
                    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Context->ScreenshotPath), true);
                    FScreenshotRequest::RequestScreenshot(Context->ScreenshotPath, true, false);
                }
                return FString();
            },
            [Context]
            {
                return !Context->bCapture || IFileManager::Get().FileExists(*Context->ScreenshotPath)
                           ? FStepResult::Passed()
                           : FStepResult::Pending();
            })
        .Finish(TEXT("Unreal <-> Isaac commands, state mirroring and emergency-stop semantics verified."));
}

void EnqueueHallScenario(FAutomationTestBase& Test)
{
    const TSharedRef<FScenarioContext> Context = MakeShared<FScenarioContext>(Test, true);
    const TSharedRef<TArray<double>> Speeds =
        MakeShared<TArray<double>>(TArray<double>{0.20, 0.35, 0.50, 0.65});
    int32 BasePort = 9847;
    FParse::Value(FCommandLine::Get(), TEXT("FactoryTestBasePort="), BasePort);
    FScenario Scenario(Context);

    auto HallCommand = [&Scenario](const FString& Name, const FString& Command, const FString& Mode,
                                   bool bAccepted = true, FString Check = {})
    {
        Scenario.Step(
            Name, 10.0,
            [Command]
            {
                return SendAll(Command);
            },
            [Mode, bAccepted]
            {
                const TArray<ASmartFactoryCellActor*> Cells = FindCells();
                if (Cells.Num() != 4)
                {
                    return FStepResult::Failed(TEXT("Hall cells are unavailable."));
                }
                if (!AreAllAcknowledged(Cells, bAccepted))
                {
                    return FStepResult::Pending();
                }
                return AreAllInMode(Cells, Mode) ? FStepResult::Passed() : FStepResult::Pending();
            },
            MoveTemp(Check));
    };

    Scenario.Wait(
        TEXT("Wait for four live factory cells"), 20.0,
        [BasePort]
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != 4)
            {
                return FStepResult::Pending();
            }
            for (int32 Index = 0; Index < Cells.Num(); ++Index)
            {
                UIsaacBridgeComponent* Bridge = Cells[Index]->GetBridge();
                if (!Bridge || Bridge->Port != BasePort + Index)
                {
                    return FStepResult::Failed(TEXT("Unexpected hall bridge port."));
                }
                TInlineComponentArray<UStaticMeshComponent*> Meshes(Cells[Index]);
                if (Meshes.Num() != 120 || Cells[Index]->bProductPoolOverflow)
                {
                    return FStepResult::Failed(TEXT("Authored mesh pool changed during simulation."));
                }
                if (!Bridge->bHasFreshState)
                {
                    return FStepResult::Pending();
                }
            }
            return FStepResult::Passed();
        },
        FString::Printf(TEXT("Four live Isaac cells on independent ports %d-%d"), BasePort, BasePort + 3));

    HallCommand(TEXT("Reset all cells"), TEXT("reset"), TEXT("paused"));

    Scenario.Step(
        TEXT("Set independent conveyor speeds"), 10.0,
        [Speeds]
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != Speeds->Num())
            {
                return FString(TEXT("Hall cells are unavailable."));
            }
            for (int32 Index = 0; Index < Cells.Num(); ++Index)
            {
                if (!Cells[Index]->GetBridge()->SendConveyorSpeed((*Speeds)[Index]))
                {
                    return FString(TEXT("Unable to queue per-cell speed."));
                }
            }
            return FString();
        },
        [Speeds]
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != Speeds->Num() || !AreAllAcknowledged(Cells))
            {
                return FStepResult::Pending();
            }
            if (!AreAllInMode(Cells, TEXT("paused")))
            {
                return FStepResult::Failed(TEXT("Speed change resumed a paused cell."));
            }
            for (int32 Index = 0; Index < Cells.Num(); ++Index)
            {
                if (!FMath::IsNearlyEqual(Cells[Index]->GetBridge()->ConveyorSpeedSetpoint, (*Speeds)[Index],
                                          1e-6))
                {
                    return FStepResult::Pending();
                }
            }
            return FStepResult::Passed();
        },
        TEXT("Four independent speed setpoints acknowledged; speed changes preserve pause"));

    Scenario.Wait(
        TEXT("Verify camera navigation"), 1.0,
        []
        {
            ASmartFactoryPlayerController* Controller = FindController();
            return Controller && Controller->VerifyCameraNavigation()
                       ? FStepResult::Passed()
                       : FStepResult::Failed(TEXT("Camera navigation transform checks failed."));
        },
        TEXT("Camera look, orbit, pan, zoom, cell focus and overview restoration verified"));

    Scenario.Step(
        TEXT("Resume all cells"), 20.0,
        []
        {
            return SendAll(TEXT("resume"));
        },
        [Speeds]
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != Speeds->Num() || !AreAllAcknowledged(Cells) ||
                !AreAllInMode(Cells, TEXT("running")) || Cells[0]->GetBridge()->SimulationTime <= 1.0)
            {
                return FStepResult::Pending();
            }
            for (int32 Index = 0; Index < Cells.Num(); ++Index)
            {
                if (!FMath::IsNearlyEqual(Cells[Index]->GetBridge()->EffectiveConveyorSpeed, (*Speeds)[Index],
                                          1e-6))
                {
                    return FStepResult::Failed(TEXT("Running belt speed differs from selected speed."));
                }
            }
            return FStepResult::Passed();
        },
        TEXT("All four moving belts report their distinct requested speed"));

    Scenario.Step(
        TEXT("Pause one selected cell"), 10.0,
        []
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            return Cells.Num() == 4 && Cells[1]->GetBridge()->SendCommand(TEXT("pause"))
                       ? FString()
                       : TEXT("Unable to pause the selected cell.");
        },
        [Context]
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != 4 || !IsAcknowledged(Cells[1]->GetBridge()) ||
                Cells[1]->GetBridge()->Mode != TEXT("paused"))
            {
                return FStepResult::Pending();
            }
            Context->FrozenTimes.Reset();
            for (const ASmartFactoryCellActor* Cell : Cells)
            {
                Context->FrozenTimes.Add(Cell->GetBridge()->SimulationTime);
            }
            return FStepResult::Passed();
        });

    Scenario.Step(
        TEXT("Verify independent cell pause"), 2.0,
        [Context]
        {
            Context->PhaseStartedAt = FPlatformTime::Seconds();
            return FString();
        },
        [Context]
        {
            if (FPlatformTime::Seconds() - Context->PhaseStartedAt < 0.75)
            {
                return FStepResult::Pending();
            }
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != 4 || Context->FrozenTimes.Num() != 4)
            {
                return FStepResult::Failed(TEXT("Hall cells are unavailable."));
            }
            for (int32 Index = 0; Index < Cells.Num(); ++Index)
            {
                const double Delta = Cells[Index]->GetBridge()->SimulationTime - Context->FrozenTimes[Index];
                if (Index == 1 ? FMath::Abs(Delta) > 1e-6 : Delta < 0.1)
                {
                    return FStepResult::Failed(TEXT("Pausing selected cell affected independent operation."));
                }
            }
            return FStepResult::Passed();
        },
        TEXT("Selected cell pause freezes only that cell; three other clocks advance"));

    Scenario.Step(
        TEXT("Resume selected cell"), 10.0,
        []
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            return Cells.Num() == 4 && Cells[1]->GetBridge()->SendCommand(TEXT("resume"))
                       ? FString()
                       : TEXT("Unable to resume the selected cell.");
        },
        []
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            return Cells.Num() == 4 && IsAcknowledged(Cells[1]->GetBridge()) &&
                           Cells[1]->GetBridge()->Mode == TEXT("running")
                       ? FStepResult::Passed()
                       : FStepResult::Pending();
        });

    Scenario.Wait(
        TEXT("Wait for every cell to sort a product"), 60.0,
        []
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            return Cells.Num() == 4 && Algo::AllOf(Cells,
                                                   [](const ASmartFactoryCellActor* Cell)
                                                   {
                                                       return Cell->GetBridge()->SortedCount >= 1 &&
                                                              Cell->RenderedProductCount >= 1;
                                                   })
                       ? FStepResult::Passed()
                       : FStepResult::Pending();
        },
        TEXT("All four Isaac robot arms completed sorting and Unreal rendered the products"));

    HallCommand(TEXT("Pause all cells"), TEXT("pause"), TEXT("paused"));

    Scenario.Step(
        TEXT("Verify all rendered tool transforms"), 2.0,
        [Context]
        {
            Context->PhaseStartedAt = FPlatformTime::Seconds();
            return FString();
        },
        [Context]
        {
            if (FPlatformTime::Seconds() - Context->PhaseStartedAt < 0.5)
            {
                return FStepResult::Pending();
            }
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != 4)
            {
                return FStepResult::Failed(TEXT("Hall cells are unavailable."));
            }
            for (const ASmartFactoryCellActor* Cell : Cells)
            {
                const FString Error = VerifyToolTransform(Cell);
                if (!Error.IsEmpty())
                {
                    return FStepResult::Failed(Error);
                }
            }
            if (Context->bCapture)
            {
                IFileManager::Get().MakeDirectory(*FPaths::GetPath(Context->ScreenshotPath), true);
                FScreenshotRequest::RequestScreenshot(Context->ScreenshotPath, true, false);
            }
            return FStepResult::Passed();
        },
        TEXT("All four translated robot tools match Isaac cell-local coordinates within 0.001cm"));

    Scenario.Wait(TEXT("Wait for hall screenshot"), 5.0,
                  [Context]
                  {
                      return !Context->bCapture || IFileManager::Get().FileExists(*Context->ScreenshotPath)
                                 ? FStepResult::Passed()
                                 : FStepResult::Pending();
                  });

    HallCommand(TEXT("Emergency-stop all cells"), TEXT("emergency_stop"), TEXT("emergency_stopped"));
    HallCommand(TEXT("Reject global resume while emergency-stopped"), TEXT("resume"),
                TEXT("emergency_stopped"), false,
                TEXT("Global emergency stop latches every cell and rejects resume"));

    Scenario.Step(
        TEXT("Reset every emergency latch"), 10.0,
        []
        {
            return SendAll(TEXT("reset"));
        },
        [Speeds]
        {
            const TArray<ASmartFactoryCellActor*> Cells = FindCells();
            if (Cells.Num() != Speeds->Num() || !AreAllAcknowledged(Cells) ||
                !AreAllInMode(Cells, TEXT("paused")))
            {
                return FStepResult::Pending();
            }
            for (int32 Index = 0; Index < Cells.Num(); ++Index)
            {
                if (Cells[Index]->GetBridge()->SortedCount != 0 ||
                    !FMath::IsNearlyEqual(Cells[Index]->GetBridge()->ConveyorSpeedSetpoint, (*Speeds)[Index],
                                          1e-6))
                {
                    return FStepResult::Pending();
                }
            }
            return FStepResult::Passed();
        },
        TEXT("Reset clears all emergency latches, preserves speeds and leaves cells paused"));

    Scenario.Finish(TEXT(
        "Large hall, four Isaac cells, speed controls, camera transforms and global commands verified."));
}
} // namespace FactoryIntegration

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FFactoryBridgeIntegrationTest, "SmartFactory.Integration.Bridge",
                                 EAutomationTestFlags::ClientContext | EAutomationTestFlags::ProductFilter)

bool FFactoryBridgeIntegrationTest::RunTest(const FString& Parameters)
{
    FactoryIntegration::EnqueueBridgeScenario(*this);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FFactoryHallIntegrationTest, "SmartFactory.Integration.Hall",
                                 EAutomationTestFlags::ClientContext | EAutomationTestFlags::ProductFilter)

bool FFactoryHallIntegrationTest::RunTest(const FString& Parameters)
{
    FactoryIntegration::EnqueueHallScenario(*this);
    return true;
}

#endif
