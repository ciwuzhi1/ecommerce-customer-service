<script setup>
/**
 * 魔珐星云数字人（具身驱动 JS SDK）接入组件
 * 官方文档：https://xingyun3d.com/developers/52-183
 *
 * 设计原则：
 *  1. 业务后端 / 智能客服后端零改动；
 *  2. 本组件自包含，不侵入 App.vue 既有聊天逻辑；
 *  3. 数字人默认不连接，用户点击「连接数字人」后才按需加载 SDK 并初始化；
 *  4. 通过 defineExpose 暴露 speak()，由 App.vue 在客服回复到达时调用同步播报。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/* =============================================================
 * 一、魔珐星云配置（后端保持不变，凭据集中在此处，便于后续替换）
 * ============================================================= */
const XINGYUN_APP_ID = '0cf56c6bb6064d2ba69360a4628a1e37'
const XINGYUN_APP_SECRET = '003519dc43884202b85fe1fa2052ebee'
const XINGYUN_GATEWAY = 'https://nebula-agent.xingyun3d.com/user/v1/ttsa/session'
const SDK_SCRIPT_URL =
  'https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar@latest.js'

/* SDK 渲染容器 id（容器必须具有明确宽高，否则影响渲染效果） */
const SDK_CONTAINER_ID = 'digital-human-sdk'

/* =============================================================
 * 二、状态
 * ============================================================= */
/** idle 未连接 / loading 连接中 / ready 就绪 / error 连接失败 */
const connectionState = ref('idle')
const downloadProgress = ref(0)
const statusText = ref('数字人尚未连接')
const errorText = ref('')
const isSpeaking = ref(false)

const sdkContainer = ref(null)

let avatarSdk = null
let hasSpoken = false
let sdkScriptPromise = null

const isReady = computed(() => connectionState.value === 'ready')
const isLoading = computed(() => connectionState.value === 'loading')

const stateLabel = computed(() => {
  switch (connectionState.value) {
    case 'loading':
      return '连接中'
    case 'ready':
      return '已连接'
    case 'error':
      return '连接异常'
    default:
      return '未连接'
  }
})

const mainButtonLabel = computed(() => {
  switch (connectionState.value) {
    case 'loading':
      return '连接中…'
    case 'ready':
      return '断开连接'
    case 'error':
      return '重新连接'
    default:
      return '连接数字人'
  }
})

/* =============================================================
 * 三、按需加载官方 SDK（不改动 index.html）
 * ============================================================= */
function loadSdkScript() {
  if (window.XmovAvatar) {
    return Promise.resolve()
  }
  if (sdkScriptPromise) {
    return sdkScriptPromise
  }

  sdkScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SDK_SCRIPT_URL
    script.async = true
    script.dataset.xmovSdk = 'true'
    script.onload = () => resolve()
    script.onerror = () => {
      sdkScriptPromise = null
      reject(new Error('数字人 SDK 脚本加载失败，请检查网络。'))
    }
    document.head.appendChild(script)
  })

  return sdkScriptPromise
}

/* =============================================================
 * 四、创建 SDK 实例并初始化连接房间
 * ============================================================= */
function createAvatarSdk() {
  avatarSdk = new window.XmovAvatar({
    containerId: `#${SDK_CONTAINER_ID}`,
    appId: XINGYUN_APP_ID,
    appSecret: XINGYUN_APP_SECRET,
    gatewayServer: XINGYUN_GATEWAY,
    hardwareAcceleration: 'prefer-hardware',
    enableLogger: false,

    onMessage(message) {
      // 50001/50002 为在线/离线模式切换，属正常状态，不作为错误处理
      if (message?.code && message.code !== 50001 && message.code !== 50002) {
        errorText.value = `数字人服务异常（code=${message.code}）${message.message || ''}`
      }
    },
    onVoiceStateChange(status) {
      if (status === 'start') {
        isSpeaking.value = true
        statusText.value = '数字人正在播报…'
      } else if (status === 'end') {
        isSpeaking.value = false
        statusText.value = '数字人就绪，可继续提问'
      }
    },
    onStartSessionWarning(message) {
      console.warn('[数字人] 会话配置警告：', message)
    },
  })

  avatarSdk.init({
    initModel: 'normal',
    onDownloadProgress(progress) {
      const value = Math.max(0, Math.min(100, Number(progress) || 0))
      downloadProgress.value = value
      if (value >= 100) {
        connectionState.value = 'ready'
        statusText.value = '数字人就绪，可开始对话'
      }
    },
  })
}

async function connect() {
  if (isLoading.value || isReady.value) {
    return
  }

  connectionState.value = 'loading'
  downloadProgress.value = 0
  errorText.value = ''
  isSpeaking.value = false
  statusText.value = '正在加载数字人形象与语音资源…'

  try {
    await loadSdkScript()
    if (!window.XmovAvatar) {
      throw new Error('数字人 SDK 未正确加载。')
    }
    createAvatarSdk()
  } catch (error) {
    connectionState.value = 'error'
    statusText.value = '数字人连接失败'
    errorText.value = error instanceof Error ? error.message : '数字人连接失败。'
  }
}

function disconnect() {
  if (avatarSdk) {
    try {
      avatarSdk.destroy()
    } catch (error) {
      /* 忽略销毁异常 */
    }
    avatarSdk = null
  }
  if (sdkContainer.value) {
    // 清理 SDK 注入的 DOM，保证可重新初始化
    sdkContainer.value.innerHTML = ''
  }
  hasSpoken = false
  isSpeaking.value = false
  downloadProgress.value = 0
  errorText.value = ''
  connectionState.value = 'idle'
  statusText.value = '数字人尚未连接'
}

/* =============================================================
 * 五、对外能力：同步播报客服回复
 *    非流式一次性播报：is_start=true, is_end=true
 * ============================================================= */
function speak(text) {
  const content = String(text ?? '').trim()
  if (!content || !isReady.value || !avatarSdk) {
    return false
  }

  try {
    // 官方建议：连续两次 speak 之间先切回待机互动状态，避免被打断
    if (hasSpoken) {
      avatarSdk.interactiveidle()
    }
    avatarSdk.speak(content, true, true)
    hasSpoken = true
    return true
  } catch (error) {
    console.warn('[数字人] 播报失败：', error)
    return false
  }
}

defineExpose({ speak })

/* =============================================================
 * 六、资源清理
 * ============================================================= */
function handleBeforeUnload() {
  try {
    avatarSdk?.destroy()
  } catch (error) {
    /* 忽略 */
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  try {
    avatarSdk?.destroy()
  } catch (error) {
    /* 忽略 */
  }
  avatarSdk = null
})
</script>

<template>
  <section class="digital-human" :class="`state-${connectionState}`">
    <header class="dh-header">
      <h2>数字人助手</h2>
      <span class="dh-badge">
        <i class="dh-dot"></i>{{ stateLabel }}
      </span>
    </header>

    <!-- 横屏 16:9 舞台，背景透明，数字人直接叠在页面之上 -->
    <div class="dh-stage">
      <div :id="SDK_CONTAINER_ID" ref="sdkContainer" class="dh-canvas"></div>

      <transition name="dh-fade">
        <div v-if="!isReady" class="dh-overlay">
          <!-- 加载中：数字人加载效果 -->
          <template v-if="isLoading">
            <div class="dh-loading-visual">
              <span class="dh-orbit"></span>
              <span class="dh-orbit dh-orbit-delay"></span>
              <span class="dh-core"></span>
            </div>
            <p class="dh-overlay-title">正在连接数字人…</p>
            <div class="dh-progress">
              <span
                class="dh-progress-bar"
                :style="{ width: `${downloadProgress}%` }"
              ></span>
            </div>
            <p class="dh-overlay-sub">
              正在下载形象与语音资源 {{ Math.round(downloadProgress) }}%，
              首次连接耗时较长，请稍候
            </p>
          </template>

          <!-- 连接失败 -->
          <template v-else-if="connectionState === 'error'">
            <div class="dh-placeholder dh-placeholder-error">!</div>
            <p class="dh-overlay-title">数字人连接失败</p>
            <p class="dh-overlay-sub">{{ errorText || '请检查网络后重试' }}</p>
          </template>

          <!-- 默认未连接 -->
          <template v-else>
            <div class="dh-placeholder">3D</div>
            <p class="dh-overlay-title">数字人尚未连接</p>
            <p class="dh-overlay-sub">
              点击下方「连接数字人」后，客服的每条回复都会由数字人同步播报
            </p>
          </template>
        </div>
      </transition>
    </div>

    <footer class="dh-footer">
      <p class="dh-status" :title="statusText">{{ statusText }}</p>
      <button
        type="button"
        class="dh-button"
        :class="{ 'is-danger': isReady }"
        :disabled="isLoading"
        @click="isReady ? disconnect() : connect()"
      >
        {{ mainButtonLabel }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.digital-human {
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 0;
  /* 区域背景透明，数字人直接融入页面 */
  background: transparent;
  border: none;
  box-shadow: none;
}

.dh-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.dh-header h2 {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
  letter-spacing: -0.01em;
  color: #142033;
}

.dh-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1;
  color: #4f5f77;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.32);
}

.dh-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
  transition: background 0.25s ease;
}

.state-loading .dh-dot {
  background: #f59e0b;
  animation: dhPulse 1.1s ease-in-out infinite;
}

.state-ready .dh-dot {
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
}

.state-error .dh-dot {
  background: #ef4444;
}

/* 横屏 16:9 舞台 */
.dh-stage {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: transparent;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 22px;
  overflow: hidden;
}

/* 柔和光晕，避免数字人完全悬空 */
.dh-stage::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(
    62% 72% at 50% 74%,
    rgba(37, 99, 235, 0.12),
    rgba(37, 99, 235, 0) 70%
  );
  pointer-events: none;
}

.dh-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
}

.dh-overlay {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px 24px;
  text-align: center;
  background: transparent;
}

.dh-overlay-title {
  margin: 4px 0 0;
  font-size: 17px;
  font-weight: 600;
  color: #16233a;
}

.dh-overlay-sub {
  margin: 0;
  max-width: 340px;
  font-size: 13px;
  line-height: 1.6;
  color: #5a6b83;
}

.dh-placeholder {
  display: grid;
  place-items: center;
  width: 76px;
  height: 76px;
  border-radius: 50%;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #2563eb;
  background: rgba(255, 255, 255, 0.82);
  border: 1px dashed rgba(37, 99, 235, 0.42);
}

.dh-placeholder-error {
  font-size: 26px;
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.45);
}

/* 加载动画 */
.dh-loading-visual {
  position: relative;
  display: grid;
  place-items: center;
  width: 84px;
  height: 84px;
}

.dh-core {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #22d3ee);
  animation: dhPulse 1.4s ease-in-out infinite;
}

.dh-orbit {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid rgba(37, 99, 235, 0.22);
  border-top-color: rgba(37, 99, 235, 0.9);
  animation: dhSpin 1.1s linear infinite;
}

.dh-orbit-delay {
  inset: 10px;
  border-top-color: rgba(34, 211, 238, 0.9);
  animation-duration: 1.7s;
  animation-direction: reverse;
}

.dh-progress {
  width: min(280px, 78%);
  height: 6px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.28);
  overflow: hidden;
}

.dh-progress-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #22d3ee);
  transition: width 0.3s ease;
}

@keyframes dhSpin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes dhPulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.85;
  }
  50% {
    transform: scale(1.18);
    opacity: 1;
  }
}

.dh-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.dh-status {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 13px;
  color: #55657d;
}

.dh-button {
  flex-shrink: 0;
  min-height: 44px;
  padding: 0 22px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  color: #eff6ff;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.2;
  cursor: pointer;
  box-shadow: 0 14px 28px rgba(37, 99, 235, 0.22);
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    opacity 0.16s ease;
}

.dh-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.dh-button:disabled {
  opacity: 0.62;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.dh-button.is-danger {
  background: linear-gradient(135deg, #b91c1c, #ef4444);
  box-shadow: 0 14px 28px rgba(239, 68, 68, 0.2);
}

.dh-fade-enter-active,
.dh-fade-leave-active {
  transition: opacity 0.3s ease;
}

.dh-fade-enter-from,
.dh-fade-leave-to {
  opacity: 0;
}

/* 窄屏堆叠时限制数字人舞台宽度 */
@media (max-width: 1180px) {
  .digital-human {
    width: 100%;
    max-width: 720px;
    margin-inline: auto;
  }
}
</style>
