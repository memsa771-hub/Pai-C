import {defineConfig} from 'vite';
import {fileURLToPath} from 'node:url';
const local=(name)=>fileURLToPath(new URL(name,import.meta.url));
export default defineConfig({root:local('.'),envDir:local('.'),publicDir:local('../../public'),
  resolve:{alias:[
    {find:'@/lib/api',replacement:local('fake-api.ts')},
    {find:'@/lib/workspace-context',replacement:local('fake-workspace.ts')},
    {find:'@/lib/pai-auth-context',replacement:local('fake-auth.ts')},
    {find:'@/lib/auth/service',replacement:local('fake-auth-service.ts')},
    {find:'@/lib/auth-api',replacement:local('fake-auth-api.ts')},
    {find:'@/hooks/use-polling',replacement:local('fake-hooks.ts')},
    {find:'@/hooks/use-operator-status',replacement:local('fake-hooks.ts')},
    {find:'@/hooks/use-composing-signal',replacement:local('fake-hooks.ts')},
    {find:'next/navigation',replacement:local('next.tsx')},
    {find:'next/image',replacement:local('next.tsx')},
    {find:'next/link',replacement:local('next.tsx')},
    {find:'@',replacement:local('../..')},
  ]},define:{'process.env.NODE_ENV':'"test"','process.env':{}},
  esbuild:{jsx:'automatic'},css:{postcss:local('../../postcss.config.cjs')},
  server:{host:'127.0.0.1',port:4173,strictPort:true,fs:{allow:[local('../..')]}}});
