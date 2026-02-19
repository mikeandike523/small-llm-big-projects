import { useState, useCallback } from 'react'

/**
 * Manages a string that grows incrementally via token streaming.
 *
 * Usage alongside TextPresenter:
 *   const { content, append, reset } = useAccumulatingContent()
 *   // Call append(token) on each incoming token.
 *   // Call reset() or reset(finalContent) when the stream ends.
 *   <TextPresenter content={content} streaming={isStreaming} maxHeight={480} />
 */
export function useAccumulatingContent(initial = '') {
  const [content, setContent] = useState(initial)

  const append = useCallback((token: string) => {
    setContent(prev => prev + token)
  }, [])

  const reset = useCallback((value = '') => {
    setContent(value)
  }, [])

  return { content, append, reset }
}
