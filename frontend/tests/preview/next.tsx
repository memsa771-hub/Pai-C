import React from 'react';
export default function ImageOrLink({src,href,children,fill,priority,unoptimized,...props}:any){return href?<a href={href} {...props}>{children}</a>:<img src={src} {...props}/>;}
export const useRouter=()=>({push:(url:string)=>window.location.assign(url),replace:(url:string)=>window.location.replace(url),refresh:()=>{}});
export const usePathname=()=>window.location.pathname;
export const useParams=()=>({workspaceId:'student'});
export const useSearchParams=()=>new URLSearchParams(window.location.search);
