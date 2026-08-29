/**
 * Tavily-backed WebSearchProvider plugin.
 * @module @deepseek-ai/dsh-web-search-tavily
 */

import type { Context } from "@deepseek-ai/cordis"
import { launchEnvironmentOf } from "@deepseek-ai/dsh-launch-environment"
import z from "@deepseek-ai/schemastery"
import {
  TavilySearchProvider,
  TAVILY_DEFAULT_BASE_URL,
} from "./provider.ts"

export {
  TAVILY_DEFAULT_BASE_URL,
  TAVILY_PROVIDER_ID,
  TavilySearchProvider,
} from "./provider.ts"

export const name = "web-search-tavily"
export const inject = ["web"]

export interface Config {
  apiKey?: string
  baseURL?: string
  searchDepth?: "basic" | "advanced"
  numResults?: number
}

export const Config: z<Config> = z.object({
  apiKey: z.string(),
  baseURL: z.string(),
  searchDepth: z.union(["basic", "advanced"] as const),
  numResults: z.number().step(1).min(1),
})

export function apply(ctx: Context, config: Config): void {
  const envKey = launchEnvironmentOf(ctx).get("TAVILY_API_KEY")?.value || process.env.TAVILY_API_KEY || ""
  const apiKey = config.apiKey || envKey
  ctx.web.registerSearchProvider(new TavilySearchProvider({
    apiKey,
    baseURL: config.baseURL ?? TAVILY_DEFAULT_BASE_URL,
    searchDepth: config.searchDepth ?? "basic",
    ...config.numResults !== undefined ? { numResults: config.numResults } : {},
  }))
}
