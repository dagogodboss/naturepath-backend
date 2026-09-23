/**
 * Reels / vlog preview URL helpers.
 *
 * Phase G: prefer `preview_clip_url` when the API returns a native clip.
 * Until server clips exist, apply an interim media-fragment window
 * `#t=0,seconds` on the full media URL (CDN or signed GET).
 */

export function previewMediaSrc(
  url: string | null | undefined,
  seconds = 60,
  options?: { previewClipUrl?: string | null }
): string | null {
  if (options?.previewClipUrl) return options.previewClipUrl;
  if (!url) return null;
  try {
    const base =
      typeof window !== 'undefined' && window.location?.origin
        ? window.location.origin
        : 'http://local';
    const u = new URL(url, base);
    if (u.hash) return url;
    return `${url}#t=0,${seconds}`;
  } catch {
    return `${url}#t=0,${seconds}`;
  }
}

/** Resolve the best playable preview src for a reel/vlog post. */
export function reelPreviewSrc(post: {
  media_url?: string | null;
  preview_clip_url?: string | null;
  preview_seconds?: number | null;
} | null | undefined): string | null {
  if (!post) return null;
  return previewMediaSrc(post.media_url, post.preview_seconds || 60, {
    previewClipUrl: post.preview_clip_url,
  });
}

function youtubeId(url: string): string | null {
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase();
    if (host === 'youtu.be' || host === 'www.youtu.be') {
      return u.pathname.replace('/', '').split('/')[0] || null;
    }
    if (host === 'youtube.com' || host.endsWith('.youtube.com')) {
      if (u.pathname.startsWith('/embed/')) {
        return u.pathname.split('/embed/')[1]?.split('/')[0] || null;
      }
      return u.searchParams.get('v');
    }
  } catch {
    return null;
  }
  return null;
}

/** Image src for a vlog card. Never falls back to a video file URL. */
export function cardPosterSrc(post: {
  cover_url?: string | null;
  embed_url?: string | null;
  media_url?: string | null;
} | null | undefined): string | null {
  if (!post) return null;
  if (post.cover_url) return post.cover_url;
  for (const candidate of [post.embed_url, post.media_url]) {
    if (!candidate) continue;
    const id = youtubeId(candidate);
    if (id) return `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;
  }
  return null;
}

export function embedIframeSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    const host = u.hostname.toLowerCase();
    const isYoutube =
      host === 'youtu.be' ||
      host === 'www.youtu.be' ||
      host === 'youtube.com' ||
      host === 'www.youtube.com' ||
      host === 'm.youtube.com' ||
      host.endsWith('.youtube.com');
    const isVimeo =
      host === 'vimeo.com' ||
      host === 'www.vimeo.com' ||
      host === 'player.vimeo.com' ||
      host.endsWith('.vimeo.com');
    if (isYoutube) {
      if (host === 'youtu.be' || host === 'www.youtu.be') {
        return `https://www.youtube.com/embed/${u.pathname.replace('/', '')}`;
      }
      const id = u.searchParams.get('v');
      if (id) return `https://www.youtube.com/embed/${id}`;
      if (u.pathname.startsWith('/embed/')) {
        return `https://www.youtube.com${u.pathname}${u.search}`;
      }
      return null;
    }
    if (isVimeo) {
      const id = u.pathname.split('/').filter(Boolean).pop();
      if (id) return `https://player.vimeo.com/video/${id}`;
    }
    const isFacebook =
      host === 'facebook.com' ||
      host.endsWith('.facebook.com') ||
      host === 'fb.watch' ||
      host.endsWith('.fb.watch');
    if (isFacebook) {
      return `https://www.facebook.com/plugins/video.php?href=${encodeURIComponent(url)}&show_text=false`;
    }
  } catch {
    return null;
  }
  return null;
}
