/**
 * Reels / vlog preview URL helpers (Phase F interim + G clip prefer).
 */
import { describe, expect, it } from 'vitest';
import { embedIframeSrc, previewMediaSrc, reelPreviewSrc } from './previewMedia';

describe('previewMediaSrc', () => {
  it('prefers Phase G preview_clip_url when present', () => {
    expect(
      previewMediaSrc('https://cdn.example/full.mp4', 60, {
        previewClipUrl: 'https://cdn.example/clip.mp4',
      })
    ).toBe('https://cdn.example/clip.mp4');
  });

  it('applies interim #t=0,seconds fragment', () => {
    expect(previewMediaSrc('https://cdn.example/full.mp4', 60)).toBe(
      'https://cdn.example/full.mp4#t=0,60'
    );
    expect(previewMediaSrc('https://cdn.example/full.mp4', 30)).toBe(
      'https://cdn.example/full.mp4#t=0,30'
    );
  });

  it('does not double-hash existing fragments', () => {
    expect(previewMediaSrc('https://cdn.example/full.mp4#t=0,10', 60)).toBe(
      'https://cdn.example/full.mp4#t=0,10'
    );
  });

  it('returns null for empty url', () => {
    expect(previewMediaSrc(null)).toBeNull();
    expect(previewMediaSrc(undefined)).toBeNull();
  });
});

describe('reelPreviewSrc', () => {
  it('uses preview_seconds and clip when set', () => {
    expect(
      reelPreviewSrc({
        media_url: 'https://cdn.example/r.mp4',
        preview_seconds: 45,
      })
    ).toBe('https://cdn.example/r.mp4#t=0,45');
    expect(
      reelPreviewSrc({
        media_url: 'https://cdn.example/r.mp4',
        preview_clip_url: 'https://cdn.example/p.mp4',
      })
    ).toBe('https://cdn.example/p.mp4');
  });
});

describe('embedIframeSrc', () => {
  it('converts youtube and vimeo watch URLs', () => {
    expect(embedIframeSrc('https://www.youtube.com/watch?v=abc123')).toContain(
      '/embed/abc123'
    );
    expect(embedIframeSrc('https://youtu.be/xyz')).toContain('/embed/xyz');
    expect(embedIframeSrc('https://vimeo.com/12345')).toContain(
      'player.vimeo.com/video/12345'
    );
  });

  it('rejects lookalike hosts and non-http schemes', () => {
    expect(embedIframeSrc('https://youtube.com.evil.example/watch?v=abc')).toBeNull();
    expect(embedIframeSrc('javascript:alert(1)')).toBeNull();
  });
});
