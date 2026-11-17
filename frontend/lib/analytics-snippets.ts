// The inline analytics snippets of the root layout. A page whose path carries a one-time token (the guardian link,
// a shared conversation) must never reach a third party: on those paths nothing is loaded or initialised, and the
// PostHog `before_send` drops any event that still comes up (a client-side move onto such a page).

/** Paths that carry a secret in the URL. */
export const PRIVATE_PATH_PREFIXES = ['/guardian/', '/share/'] as const;

export function isPrivatePath(path: string): boolean {
  return PRIVATE_PATH_PREFIXES.some((prefix) => path.startsWith(prefix));
}

const PRIVATE_TEST = `${JSON.stringify(PRIVATE_PATH_PREFIXES)}.some(function(p){return window.location.pathname.indexOf(p)===0})`;

const LOADER = String.raw`!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);`;

export function posthogSnippet(key: string, host: string): string {
  return `
(function(){
  if (${PRIVATE_TEST}) return;
  ${LOADER}
  window.posthog.init(${JSON.stringify(key)}, {
    api_host: ${JSON.stringify(host)},
    person_profiles: 'identified_only',
    // 'history_change' also fires $pageview on client-side (SPA) route changes; plain true only captures full page
    // loads, which missed every router.push navigation (e.g. the whole /settings dashboard).
    capture_pageview: 'history_change',
    capture_pageleave: true,
    autocapture: true,
    before_send: function(event){ return ${PRIVATE_TEST} ? null : event; }
  });
})();
`;
}

export function gaSnippet(id: string): string {
  return `
(function(){
  if (${PRIVATE_TEST}) return;
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(${JSON.stringify(id)});
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  function gtag(){window.dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', ${JSON.stringify(id)});
})();
`;
}
