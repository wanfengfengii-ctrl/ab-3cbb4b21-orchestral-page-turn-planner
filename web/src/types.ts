export interface ObjectiveVector {
  pages: number;
  unsafeTurns: number;
  maxGapMs: number;
  sumSquaredSlack: number;
}

export interface TurnInfo {
  restAfterMs: number;
  requiredMs: number;
  safe: boolean;
  gapMs: number;
}

export interface PageInfo {
  page: number;
  startMeasure: number;
  endMeasure: number;
  measureCount: number;
  usedHeight: number;
  remainingCapacity: number;
  isLastPage: boolean;
  turn: TurnInfo | null;
}

export interface SolveResponse {
  objective: ObjectiveVector;
  turnPoints: number[];
  pageEndIndices: number[];
  pages: PageInfo[];
}

export interface ApiError {
  path: string;
  message: string;
}
