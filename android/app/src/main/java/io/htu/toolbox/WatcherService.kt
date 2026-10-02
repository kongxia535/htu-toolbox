package io.htu.toolbox

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.IBinder
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

data class ConnectionState(val running: Boolean = false, val online: Boolean? = null,
    val message: String = "保存账号后，即可开始自动登录", val lastRun: Long = 0, val nextRun: Long = 0)
object LiveStatus { val state = AtomicReference(ConnectionState()) }

class WatcherService : Service() {
    private val executor = Executors.newSingleThreadScheduledExecutor()
    private var started = false
    @Volatile private var stopping = false
    private var failures = 0
    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "校园网自动登录", NotificationManager.IMPORTANCE_LOW))
    }
    private fun notification(message: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, WatcherService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_app).setContentTitle("HTU Connect · 自动登录中")
            .setContentText(message).setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this, R.drawable.ic_app), "停止", stop).build()).build()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            Credentials(this).enable(false); stopSelf(); return START_NOT_STICKY
        }
        startForeground(1, notification("正在检测校园网络"))
        if (!Credentials(this).configured() || !Credentials(this).enabled()) {
            stopSelf(); return START_NOT_STICKY
        }
        if (!started) {
            started = true
            LiveStatus.state.updateAndGet { it.copy(running = true, message = "正在检测校园网络") }
            executor.execute { tick() }
        }
        return START_STICKY
    }
    private fun tick() {
        if (stopping) return
        val credentials = Credentials(this)
        var online: Boolean? = null
        val message = try {
            val result = PortalClient(this).check(credentials)
            online = result.first; failures = 0; result.second
        } catch (error: Exception) {
            failures++; error.message ?: "检测失败，请检查校园网络"
        }
        if (stopping) return
        val interval = credentials.account().interval.toLong()
        val delay = (interval * (1L shl (failures - 1).coerceIn(0, 3))).coerceAtMost(maxOf(interval, 60L))
        LiveStatus.state.set(ConnectionState(true, online, message, System.currentTimeMillis(), System.currentTimeMillis() + delay * 1000))
        getSystemService(NotificationManager::class.java).notify(1, notification(message))
        executor.schedule({ tick() }, delay, TimeUnit.SECONDS)
    }
    override fun onDestroy() {
        stopping = true; executor.shutdownNow()
        LiveStatus.state.updateAndGet { it.copy(running = false, nextRun = 0) }
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
    companion object { const val CHANNEL = "htu-campus"; const val STOP = "io.htu.toolbox.STOP" }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val credentials = Credentials(context)
        if (credentials.configured() && credentials.enabled() && credentials.account().autoStart) {
            try { context.startForegroundService(Intent(context, WatcherService::class.java)) }
            catch (_: RuntimeException) { LiveStatus.state.set(ConnectionState(message = "系统限制了开机启动，请打开应用启动自动登录")) }
        }
    }
}
