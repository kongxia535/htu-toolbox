package io.htu.toolbox

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.*
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val accent = Color.rgb(17,119,109)
    private val ink = Color.rgb(32,45,42)
    private val muted = Color.rgb(115,128,122)
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var credentials: Credentials
    private lateinit var status: TextView
    private lateinit var result: TextView
    private lateinit var account: EditText
    private lateinit var password: EditText
    private lateinit var portal: EditText
    private lateinit var interval: EditText
    private lateinit var operator: Spinner
    private lateinit var autoStart: Switch
    private val controls = mutableListOf<View>()
    private var busy = false
    private var pendingStart = false
    private val operators = listOf("lt", "yd", "dx", "hsd")
    private val update = object : Runnable {
        override fun run() {
            val value = LiveStatus.state.get()
            status.text = when { value.running -> "● 自动登录已开启"; credentials.configured() -> "○ 自动登录已暂停"; else -> "○ 等待账号配置" }
            result.text = if(value.lastRun > 0) getString(R.string.last_check, value.message,
                SimpleDateFormat("HH:mm:ss",Locale.getDefault()).format(Date(value.lastRun))) else value.message
            handler.postDelayed(this, 1000)
        }
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun background(color: Int, radius: Int = 18) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun label(text: String, size: Float = 13f, color: Int = ink) = TextView(this).apply {
        this.text = text; textSize = size; setTextColor(color); setPadding(0,dp(8),0,dp(8))
    }
    private fun card(parent: LinearLayout, title: String, caption: String): LinearLayout {
        val view = column().apply {
            background = background(Color.WHITE); setPadding(dp(22),dp(18),dp(22),dp(22))
            layoutParams = LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(16) }
        }
        view.addView(label(caption,10f,accent));view.addView(label(title,21f).apply { typeface=Typeface.DEFAULT_BOLD })
        parent.addView(view);return view
    }
    private fun field(parent: LinearLayout, title: String, hint: String, type: Int = InputType.TYPE_CLASS_TEXT): EditText {
        parent.addView(label(title,12f,muted))
        val input = EditText(this).apply {
            this.hint=hint; inputType=type; textSize=14f;setTextColor(ink);setHintTextColor(muted)
            background=background(Color.rgb(244,246,243),10);setPadding(dp(12),dp(10),dp(12),dp(10))
            layoutParams=LinearLayout.LayoutParams(-1,-2).apply{bottomMargin=dp(8)}
            minHeight=dp(48)
        }
        parent.addView(input);controls.add(input);return input
    }
    private fun button(parent: LinearLayout, text: String, primary: Boolean = false, action: () -> Unit) {
        val view = Button(this).apply {
            this.text=text;isAllCaps=false;textSize=13f;setTextColor(if(primary) Color.WHITE else accent)
            background=background(if(primary) accent else Color.rgb(231,243,238),12)
            layoutParams=LinearLayout.LayoutParams(-1,dp(50)).apply{topMargin=dp(10)}
            setOnClickListener { if(!busy) action() }
        }
        parent.addView(view);controls.add(view)
    }
    private fun work(action: () -> String) {
        if(busy)return
        busy=true;controls.forEach { it.isEnabled=false }
        executor.execute {
            val message=try { action() } catch(error:Exception) { error.message ?: "操作失败，请重试" }
            runOnUiThread {
                if(isDestroyed)return@runOnUiThread
                busy=false;controls.forEach{it.isEnabled=true};Toast.makeText(this,message,Toast.LENGTH_LONG).show()
                LiveStatus.state.updateAndGet{it.copy(message=message,lastRun=System.currentTimeMillis())}
            }
        }
    }
    private fun startWatcher() {
        if(Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) {
            pendingStart=true;requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),100);return
        }
        credentials.enable(true)
        try { startForegroundService(Intent(this,WatcherService::class.java)) }
        catch (_:RuntimeException) { credentials.enable(false);Toast.makeText(this,"系统阻止了后台启动，请重试",Toast.LENGTH_LONG).show() }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if(requestCode==100 && pendingStart) {
            pendingStart=false
            if(grantResults.firstOrNull()==PackageManager.PERMISSION_GRANTED)startWatcher()
            else Toast.makeText(this,"允许通知后才能开启可见的后台自动登录",Toast.LENGTH_LONG).show()
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState);credentials=Credentials(this)
        val root=column().apply {setPadding(dp(18),dp(12),dp(18),dp(24));background=background(Color.rgb(246,247,244),0)}
        val scroll=ScrollView(this).apply{isFillViewport=true;addView(root)};setContentView(scroll)
        if(Build.VERSION.SDK_INT>=30)scroll.setOnApplyWindowInsetsListener { view,insets ->
            val bars=insets.getInsets(WindowInsets.Type.systemBars());view.setPadding(bars.left,bars.top,bars.right,bars.bottom);insets
        }
        root.addView(label("H·   HTU Connect",20f,accent).apply{typeface=Typeface.DEFAULT_BOLD})
        root.addView(label("YOUR CAMPUS, CONNECTED",10f,muted))
        root.addView(label("保持连接，\n专注当下。",34f).apply{typeface=Typeface.DEFAULT_BOLD})
        root.addView(label("让校园网自动连接，把时间留给更重要的事。",12f,muted))
        status=label("正在读取状态",13f,accent);root.addView(status)
        val accountCard=card(root,"连接你的校园","01 / ACCOUNT")
        account=field(accountCard,"上网账号","输入学号或上网账号")
        accountCard.addView(label("运营商",12f,muted))
        operator=Spinner(this).apply{adapter=ArrayAdapter(this@MainActivity,android.R.layout.simple_spinner_dropdown_item,listOf("中国联通","中国移动","中国电信","校园本地账号"))}
        accountCard.addView(operator);controls.add(operator)
        password=field(accountCard,"上网密码 · Android Keystore 加密","已有密码可留空保留",InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        portal=field(accountCard,"校园门户地址","http://10.101.2.194:6060/portal.do?...",InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE)
        button(accountCard,"自动获取门户地址") {
            work { val detected=PortalClient(this).detect();runOnUiThread{portal.setText(detected)};"门户已获取，请保存并连接" }
        }
        interval=field(accountCard,"检测间隔 / 秒","10",InputType.TYPE_CLASS_NUMBER)
        autoStart=Switch(this).apply{text="开机后恢复自动登录";textSize=12f;setTextColor(ink)};accountCard.addView(autoStart);controls.add(autoStart)
        button(accountCard,"保存并连接 →",true) {
            val updated=Account(account.text.toString().trim(),operators[operator.selectedItemPosition],portal.text.toString().trim(),interval.text.toString().toIntOrNull()?:0,autoStart.isChecked)
            val secret=password.text.toString()
            work { credentials.save(updated,secret);runOnUiThread{password.setText("");startWatcher()};"配置已保存" }
        }
        accountCard.addView(label("密码只在本机解密。应用数据不参与系统备份。",10f,muted))
        val controlCard=card(root,"连接，由你掌控","02 / CONTROL")
        button(controlCard,"立即检测",true){work{PortalClient(this).check(credentials).let{(online,message)->LiveStatus.state.updateAndGet{it.copy(online=online)};message}}}
        button(controlCard,"立即登录"){work{PortalClient(this).check(credentials,true).let{(online,message)->LiveStatus.state.updateAndGet{it.copy(online=online)};message}}}
        button(controlCard,"启动自动登录"){if(credentials.configured())startWatcher() else Toast.makeText(this,"请先保存账号配置",Toast.LENGTH_SHORT).show()}
        button(controlCard,"停止自动登录"){credentials.enable(false);stopService(Intent(this,WatcherService::class.java))}
        result=label("",12f,muted);controlCard.addView(result)
        root.addView(label("后台运行时保持常驻通知。部分系统需要允许后台运行；仅在设备连接校园网络时可认证。",11f,muted))
        root.addView(label("HTU Connect  /  为校园生活，保持连接。",10f,accent))
        val config=credentials.account();account.setText(config.id);operator.setSelection(operators.indexOf(config.operator).coerceAtLeast(0));portal.setText(config.portal);interval.setText(String.format(Locale.ROOT,"%d",config.interval));autoStart.isChecked=config.autoStart
    }
    override fun onResume(){super.onResume();handler.post(update)}
    override fun onPause(){handler.removeCallbacks(update);super.onPause()}
    override fun onDestroy(){executor.shutdownNow();super.onDestroy()}
}
