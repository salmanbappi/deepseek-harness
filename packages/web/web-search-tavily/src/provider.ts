/**
 * TavilySearchProvider: a WebSearchProvider backed by the Tavily search API.
 * @module @deepseek-ai/dsh-web-search-tavily/provider
 */

import { WebError } from "@deepseek-ai/dsh-web"
import type {
  WebSearchProvider,
  WebSearchRequest,
  WebSearchResult,
  WebSearchSource,
} from "@deepseek-ai/dsh-web"
import type { TavilyError, TavilyResultItem, TavilySearchResponse } from "./types.ts"

export const TAVILY_PROVIDER_ID = "tavily"
export const TAVILY_DEFAULT_BASE_URL = "https://api.tavily.com"
const USER_AGENT = "deepseek-harness/0.0.1"

export interface TavilySearchProviderOptions {
  apiKey: string
  baseURL?: string
  searchDepth?: "basic" | "advanced"
  numResults?: number
}

export function mapTavilyResult(result: TavilyResultItem): WebSearchSource | undefined {
  if (!result.url) return undefined
  return {
    url: result.url,
    ...result.title != null && result.title.length > 0 ? { title: result.title } : {},
    snippet: result.content?.trim() || "",
    ...result.published_date != null && result.published_date.length > 0 ? { publishedAt: result.published_date } : {},
  }
}

export function mapTavilyResponse(response: TavilySearchResponse): WebSearchResult {
  const sources = (response.results ?? [])
    .map(mapTavilyResult)
    .filter((source): source is WebSearchSource => source !== undefined)
  return {
    sources,
    truncated: false,
    ...response.answer != null && response.answer.length > 0 ? { content: response.answer } : {},
  }
}

export class TavilySearchProvider implements WebSearchProvider {
  readonly id = TAVILY_PROVIDER_ID

  constructor(private readonly options: TavilySearchProviderOptions) {}

  available(): boolean {
    return typeof this.options.apiKey === "string" && this.options.apiKey.trim().length > 0
  }

  async search(request: WebSearchRequest, signal?: AbortSignal): Promise<WebSearchResult> {
    const numResults = request.maxResults ?? this.options.numResults ?? 5
    const endpoint = (this.options.baseURL || TAVILY_DEFAULT_BASE_URL).replace(/\/+$/, "") + "/search"

    let response: Response
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "User-Agent": USER_AGENT,
        },
        body: JSON.stringify({
          api_key: this.options.apiKey,
          query: request.query,
          max_results: numResults,
          search_depth: this.options.searchDepth ?? "basic",
          include_answer: true,
        }),
        signal,
      })
    } catch (error: unknown) {
      if (signal?.aborted) throw new WebError("search aborted", "WEB_ABORTED")
      throw new WebError(`Tavily search network request failed: ${String(error)}`, "WEB_PROVIDER_ERROR", { cause: error })
    }

    if (!response.ok) {
      let message = `Tavily search failed with HTTP status ${response.status}`
      try {
        const body = (await response.json()) as TavilyError
        if (body.error) message = `Tavily: ${body.error}`
        else if (body.message) message = `Tavily: ${body.message}`
      } catch {}
      throw new WebError(message, "WEB_PROVIDER_ERROR")
    }

    try {
      const payload = (await response.json()) as TavilySearchResponse
      return mapTavilyResponse(payload)
    } catch (error: unknown) {
      throw new WebError(`Tavily returned invalid response: ${String(error)}`, "WEB_PROVIDER_ERROR", { cause: error })
    }
  }
}
