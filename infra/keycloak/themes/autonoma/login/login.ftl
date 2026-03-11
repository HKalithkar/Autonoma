<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Autonoma</title>
    
    <#-- Link to your custom CSS -->
    <link rel="stylesheet" href="${url.resourcesPath}/css/styles.css">

    <#-- Optional: If you want to use Tailwind via CDN just for this page -->
    <script src="https://cdn.tailwindcss.com"></script>
</head>

<body class="font-sans text-slate-50 min-h-screen">
    
    <div class="auth-split-layout">
        
        <#-- Left Side: Login Form -->
        <div class="auth-form-side">
            <div class="auth-form-container">
                
                <#-- Custom Header -->
                <div class="brand-header text-center sm:text-left mb-2">
                    <span class="app-kicker block text-xs font-semibold tracking-widest text-slate-400 uppercase mb-1">Control Plane</span>
                    <h1 class="text-4xl sm:text-5xl font-bold text-slate-900 tracking-tight mb-2">Autonoma</h1>
                    <p class="app-tagline text-sm text-slate-500">Please log in to continue</p>
                </div>

                <#-- Error Message Block -->
                <#if message?has_content>
                    <div class="mb-4 p-3 rounded bg-red-50 border border-red-200 text-red-600 text-sm">
                        ${message.summary}
                    </div>
                </#if>

                <#-- THE LOGIN FORM -->
                <form id="kc-form-login" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" class="space-y-5 w-full">
                    
                    <div>
                        <label for="username" class="block text-sm font-medium text-slate-600 mb-1">
                            <#if !realm.loginWithEmailAllowed>Username<#elseif !realm.registrationEmailAsUsername>Username or email<#else>Email</#if>
                        </label>
                        <input tabindex="1" id="username" name="username" value="${(login.username!'')}" type="text" autofocus autocomplete="off" 
                            class="w-full bg-white border border-slate-300 rounded-xl px-4 py-3 text-slate-800 shadow-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors" />
                    </div>

                    <div>
                        <label for="password" class="block text-sm font-medium text-slate-600 mb-1">Password</label>
                        <input tabindex="2" id="password" name="password" type="password" autocomplete="off" 
                            class="w-full bg-white border border-slate-300 rounded-xl px-4 py-3 text-slate-800 shadow-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors" />
                    </div>

                    <div class="pt-2">
                        <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                        <button tabindex="4" name="login" id="kc-login" type="submit" 
                            class="auth-submit-btn text-white font-semibold shadow-md interactive-hover">
                            Sign In
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
                        </button>
                    </div>
                </form>

                <#-- Registration Link -->
                <#if realm.password && realm.registrationAllowed && !registrationDisabled>
                    <div class="mt-4 text-center sm:text-left text-sm text-slate-500">
                        <span>New here? <a tabindex="6" href="${url.registrationUrl}" class="text-blue-600 hover:text-blue-500 font-medium transition-colors">Register for an account</a></span>
                    </div>
                </#if>
                
            </div>
        </div>

        <#-- Right Side: Terminal Visuals -->
        <div class="auth-visual-side">
            <div class="terminal-window">
                <div class="terminal-header">
                    <div class="terminal-dots">
                        <div class="dot red"></div>
                        <div class="dot yellow"></div>
                        <div class="dot green"></div>
                    </div>
                    <div class="terminal-title">bash - autonoma</div>
                </div>
                <div class="terminal-body">
                    <div class="log-line animate-line-1">
                        <span class="ts">[10:42:01]</span> <span class="info">INFO</span> Initializing control plane module...
                    </div>
                    <div class="log-line animate-line-2">
                        <span class="ts">[10:42:02]</span> <span class="info">INFO</span> Connecting to autonomous agents...
                    </div>
                    <div class="log-line animate-line-3">
                        <span class="ts">[10:42:05]</span> <span class="success">SUCCESS</span> 4 agents online and syncing.
                    </div>
                    <div class="log-line animate-line-4">
                        <span class="ts">[10:42:08]</span> <span class="warn">WARN</span> Awaiting user authentication sequence.
                    </div>
                    <div class="log-line animate-line-5">
                        <span class="ts">[10:42:09]</span> <span class="info">SYS</span> Ready for input <span class="cursor-blink">_</span>
                    </div>
                </div>
            </div>
        </div>
        
    </div>

</body>
</html>