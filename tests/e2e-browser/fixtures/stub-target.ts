import { createServer, type IncomingMessage, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { scheduler } from 'node:timers/promises';

export interface StubCall {
  path: string;
  method: string;
  headers: IncomingMessage['headers'];
  body: string;
}

interface StubState {
  reply: string;
  /** A scripted reply list: each call takes the next one, the last one repeats (used by the adaptive run). */
  replies: string[];
  delayMs: number;
  calls: StubCall[];
}

const DEFAULT_REPLY = 'The agent refused.';

async function readBody(request: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString('utf8');
}

/**
 * A tiny deterministic HTTP target. It answers any path with `{"reply": "<configured text>"}` and records every
 * request, so a spec can force a canary leak or count exactly how many attack messages were sent.
 */
export class StubTarget {
  constructor(
    private readonly server: Server,
    private readonly state: StubState,
    readonly url: string,
  ) {}

  get requests(): readonly StubCall[] {
    return this.state.calls;
  }

  /** The parsed JSON body of each recorded request (empty object when the body is not JSON). */
  get jsonBodies(): Array<Record<string, unknown>> {
    return this.state.calls.map((call) =>
      call.body.trim().startsWith('{') ? (JSON.parse(call.body) as Record<string, unknown>) : {},
    );
  }

  setReply(text: string): void {
    this.state.reply = text;
    this.state.replies = [];
  }

  /** Answer the calls in sequence; the last reply repeats for any further request. */
  setReplies(replies: string[]): void {
    this.state.replies = [...replies];
  }

  setDelay(ms: number): void {
    this.state.delayMs = ms;
  }

  resetRequests(): void {
    this.state.calls.length = 0;
  }

  async close(): Promise<void> {
    this.server.closeAllConnections();
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }
}

export async function startStubTarget(): Promise<StubTarget> {
  const state: StubState = { reply: DEFAULT_REPLY, replies: [], delayMs: 0, calls: [] };
  const server = createServer(async (request, response) => {
    const body = await readBody(request);
    state.calls.push({
      path: request.url ?? '/',
      method: request.method ?? 'GET',
      headers: request.headers,
      body,
    });
    if (state.delayMs > 0) {
      await scheduler.wait(state.delayMs);
    }
    const reply = state.replies.length > 1 ? (state.replies.shift() as string) : (state.replies[0] ?? state.reply);
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ reply }));
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  const address = server.address() as AddressInfo;
  return new StubTarget(server, state, `http://127.0.0.1:${address.port}/chat`);
}
