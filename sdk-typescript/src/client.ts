import { HttpClient } from "./http.js";
import { MemoryResource } from "./resources/memory.js";
import { ActionsResource } from "./resources/actions.js";
import { ContextResource } from "./resources/context.js";
import { AgentsResource } from "./resources/agents.js";
import { SessionsResource } from "./resources/sessions.js";
import { EpisodesResource } from "./resources/episodes.js";
import type { CrewLayerClientOptions } from "./types.js";

const DEFAULT_BASE_URL = "http://localhost:8000";

export class CrewLayerClient {
  readonly memory: MemoryResource;
  readonly actions: ActionsResource;
  readonly context: ContextResource;
  readonly agents: AgentsResource;
  readonly sessions: SessionsResource;
  readonly episodes: EpisodesResource;

  /** @internal */
  readonly _http: HttpClient;

  constructor(options: CrewLayerClientOptions = {}) {
    const apiKey =
      options.apiKey ??
      (typeof process !== "undefined" ? process.env["CREWLAYER_API_KEY"] : undefined) ??
      "";

    const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;

    this._http = new HttpClient({
      baseUrl,
      apiKey,
      maxRetries: options.maxRetries,
      timeout: options.timeout,
    });

    this.memory = new MemoryResource(this._http);
    this.actions = new ActionsResource(this._http);
    this.context = new ContextResource(this._http);
    this.agents = new AgentsResource(this._http);
    this.sessions = new SessionsResource(this._http);
    this.episodes = new EpisodesResource(this._http);
  }
}
