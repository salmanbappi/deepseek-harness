/**
 * Wire types for Tavily search API (POST https://api.tavily.com/search).
 * @module @deepseek-ai/dsh-web-search-tavily/types
 */

export interface TavilySearchRequest {
  api_key: string
  query: string
  max_results?: number
  search_depth?: "basic" | "advanced"
  include_answer?: boolean
}

export interface TavilyResultItem {
  title?: string | null
  url: string
  content?: string | null
  score?: number
  published_date?: string | null
}

export interface TavilySearchResponse {
  query: string
  answer?: string | null
  results?: TavilyResultItem[]
}

export interface TavilyError {
  error?: string
  message?: string
}
