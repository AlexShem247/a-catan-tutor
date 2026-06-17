from dataclasses import dataclass


@dataclass(frozen=True)
class DemoStateDefinition:
    moveNumber: int
    demoStateNumber: int
    description: str


DEMO_MODE_STATES = [
    DemoStateDefinition(moveNumber=1, demoStateNumber=1, description="First Opening Settlement"),
    DemoStateDefinition(moveNumber=2, demoStateNumber=2, description="First Opening Road"),
    DemoStateDefinition(moveNumber=3, demoStateNumber=3, description="Second Opening Settlement"),
    DemoStateDefinition(moveNumber=38, demoStateNumber=4, description="Building a City Recommendation"),
    DemoStateDefinition(moveNumber=55, demoStateNumber=5, description="Resource Discard Recommendation"),
    DemoStateDefinition(moveNumber=77, demoStateNumber=6, description="Trade Recommendation"),
    DemoStateDefinition(moveNumber=78, demoStateNumber=7, description="Trade Recommendation"),
    DemoStateDefinition(moveNumber=91, demoStateNumber=8, description="Development Card Recommendation"),
]
