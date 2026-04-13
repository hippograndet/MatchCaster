// frontend/src/hooks/useAudioPlayer.ts

import { useRef, useCallback, useState } from 'react'
import type { AgentName, AudioMessage } from '../utils/types'

const MAX_QUEUE_SIZE = 3

interface AudioQueueItem {
  agent: AgentName
  buffer: AudioBuffer
  text: string
  match_time: number
}

export interface PlaybackStartedEvent {
  agent: AgentName
  text: string
  match_time: number
}

export interface UseAudioPlayerReturn {
  activeAgent: AgentName | null
  isPlaying: boolean
  handleAudioMessage: (msg: AudioMessage) => void
  setMuted: (muted: boolean) => void
  muted: boolean
  setOnPlaybackStarted: (cb: ((e: PlaybackStartedEvent) => void) | null) => void
}

export function useAudioPlayer(): UseAudioPlayerReturn {
  const ctxRef = useRef<AudioContext | null>(null)
  const queueRef = useRef<AudioQueueItem[]>([])
  const isPlayingRef = useRef(false)
  const [activeAgent, setActiveAgent] = useState<AgentName | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [muted, setMutedState] = useState(false)
  const mutedRef = useRef(false)
  const onPlaybackStartedRef = useRef<((e: PlaybackStartedEvent) => void) | null>(null)

  const setOnPlaybackStarted = useCallback(
    (cb: ((e: PlaybackStartedEvent) => void) | null) => {
      onPlaybackStartedRef.current = cb
    },
    []
  )

  const getCtx = useCallback((): AudioContext => {
    if (!ctxRef.current || ctxRef.current.state === 'closed') {
      ctxRef.current = new AudioContext()
    }
    if (ctxRef.current.state === 'suspended') {
      ctxRef.current.resume().catch(console.error)
    }
    return ctxRef.current
  }, [])

  const playNext = useCallback(() => {
    if (mutedRef.current) {
      queueRef.current = []
      isPlayingRef.current = false
      setIsPlaying(false)
      setActiveAgent(null)
      return
    }

    const item = queueRef.current.shift()
    if (!item) {
      isPlayingRef.current = false
      setIsPlaying(false)
      setActiveAgent(null)
      return
    }

    const ctx = getCtx()
    const source = ctx.createBufferSource()
    source.buffer = item.buffer

    const gainNode = ctx.createGain()
    gainNode.gain.setValueAtTime(1.0, ctx.currentTime)
    source.connect(gainNode)
    gainNode.connect(ctx.destination)

    isPlayingRef.current = true
    setIsPlaying(true)
    setActiveAgent(item.agent)

    // FIX: fire callback when THIS track STARTS playing — syncs overlay text with audio
    if (onPlaybackStartedRef.current) {
      onPlaybackStartedRef.current({
        agent: item.agent,
        text: item.text,
        match_time: item.match_time,
      })
    }

    source.onended = () => {
      setTimeout(() => playNext(), 150)
    }

    source.start(0)
  }, [getCtx])

  const handleAudioMessage = useCallback(
    (msg: AudioMessage) => {
      if (!msg.audio_b64) {
        // No audio bytes — text only: fire callback immediately so overlay still shows
        if (onPlaybackStartedRef.current) {
          onPlaybackStartedRef.current({
            agent: msg.agent,
            text: msg.text,
            match_time: msg.match_time,
          })
        }
        return
      }

      const ctx = getCtx()
      const binaryStr = atob(msg.audio_b64)
      const bytes = new Uint8Array(binaryStr.length)
      for (let i = 0; i < binaryStr.length; i++) {
        bytes[i] = binaryStr.charCodeAt(i)
      }

      ctx.decodeAudioData(bytes.buffer)
        .then((buffer) => {
          const item: AudioQueueItem = {
            agent: msg.agent,
            buffer,
            text: msg.text,
            match_time: msg.match_time,
          }
          // Drop oldest if queue full
          while (queueRef.current.length >= MAX_QUEUE_SIZE) {
            queueRef.current.shift()
          }
          queueRef.current.push(item)
          if (!isPlayingRef.current) playNext()
        })
        .catch((err) => {
          console.warn('[AudioPlayer] Decode failed:', err)
          // Still show text if decode fails
          if (onPlaybackStartedRef.current) {
            onPlaybackStartedRef.current({
              agent: msg.agent,
              text: msg.text,
              match_time: msg.match_time,
            })
          }
        })
    },
    [getCtx, playNext]
  )

  const setMuted = useCallback((m: boolean) => {
    mutedRef.current = m
    setMutedState(m)
    if (m) {
      queueRef.current = []
      isPlayingRef.current = false
      setIsPlaying(false)
      setActiveAgent(null)
    }
  }, [])

  return { activeAgent, isPlaying, handleAudioMessage, setMuted, muted, setOnPlaybackStarted }
}
