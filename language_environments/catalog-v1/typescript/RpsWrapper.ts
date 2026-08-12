declare const module: unknown;
declare const require: {
  (path: string): { chooseMove: StrategyFunction };
  main: unknown;
};
declare const process: {
  env: Record<string, string | undefined>;
  exit(code: number): never;
  stderr: { write(value: string): void };
  stdin: {
    on(event: "data" | "end", callback: (value?: string) => void): void;
    setEncoding(encoding: string): void;
  };
  stdout: { write(value: string): void };
};

type StrategyFunction = (
  turn: number,
  myHistory: string,
  opponentHistory: string,
  rng: SeedAdapter,
) => string;

const MASK_64 = (1n << 64n) - 1n;
const GAMMA = 0x9e3779b97f4a7c15n;

export class SeedAdapter {
  private state: bigint;

  constructor(seed: string) {
    if (!/^(0|[1-9][0-9]*)$/.test(seed)) {
      throw new Error("RPS_SEED must be an unsigned 64-bit integer");
    }
    this.state = BigInt(seed);
    if (this.state > MASK_64) {
      throw new Error("RPS_SEED must be an unsigned 64-bit integer");
    }
  }

  nextUint64(): bigint {
    this.state = (this.state + GAMMA) & MASK_64;
    let value = this.state;
    value = ((value ^ (value >> 30n)) * 0xbf58476d1ce4e5b9n) & MASK_64;
    value = ((value ^ (value >> 27n)) * 0x94d049bb133111ebn) & MASK_64;
    return (value ^ (value >> 31n)) & MASK_64;
  }

  nextInt(upperExclusive: number): number {
    if (!Number.isSafeInteger(upperExclusive) || upperExclusive <= 0) {
      throw new Error("upperExclusive must be a positive safe integer");
    }
    const bound = BigInt(upperExclusive);
    const threshold = (MASK_64 + 1n) % bound;
    let value: bigint;
    do {
      value = this.nextUint64();
    } while (value < threshold);
    return Number(value % bound);
  }
}

function fail(message: string): never {
  process.stderr.write("TypeScript wrapper: " + message + "\n");
  return process.exit(2);
}

function main(): void {
  if (process.env.RPS_PROTOCOL_VERSION !== "1") {
    fail("unsupported RPS_PROTOCOL_VERSION");
  }
  let rng: SeedAdapter;
  try {
    rng = new SeedAdapter(process.env.RPS_SEED ?? "");
  } catch (error) {
    fail(error instanceof Error ? error.message : "invalid RPS_SEED");
  }
  const strategy = require("./strategy");
  if (typeof strategy.chooseMove !== "function") {
    fail("chooseMove function is unavailable");
  }

  process.stderr.write("RPS_READY_V1\n");
  process.stdin.setEncoding("utf8");
  let buffer = "";
  const lines: string[] = [];
  process.stdin.on("data", (chunk = "") => {
    buffer += chunk;
    while (buffer.includes("\n")) {
      const newline = buffer.indexOf("\n");
      lines.push(buffer.slice(0, newline).replace(/\r$/, ""));
      buffer = buffer.slice(newline + 1);
      if (lines.length === 3) {
        const turn = Number(lines[0]);
        if (!Number.isSafeInteger(turn)) {
          fail("Turn must be an integer");
        }
        const move = strategy.chooseMove(
          turn,
          lines[1] === "-" ? "" : lines[1],
          lines[2] === "-" ? "" : lines[2],
          rng,
        );
        process.stdout.write(String(move) + "\n");
        lines.length = 0;
      }
    }
  });
}

if (require.main === module) {
  main();
}
