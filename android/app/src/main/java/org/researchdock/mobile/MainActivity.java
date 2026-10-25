package org.researchdock.mobile;

import android.app.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.security.keystore.*;
import android.text.*;
import android.view.*;
import android.widget.*;
import android.util.Base64;
import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import java.util.*;
import java.util.concurrent.*;

/** Native private reader; no embedded server address, model key or browser bridge. */
public class MainActivity extends Activity {
 private final int GREEN=Color.rgb(36,107,83), BG=Color.rgb(246,245,240), INK=Color.rgb(32,44,42);
 private LinearLayout root,content,nav; private TextView status; private EditText search;
 private JSONArray docs=new JSONArray(); private String tab="动态",industry="全部",company="",query="";
 private final ExecutorService worker=Executors.newSingleThreadExecutor(); private volatile boolean syncing=false;
 private android.content.SharedPreferences prefs;
 @Override public void onCreate(Bundle state){super.onCreate(state);prefs=getSharedPreferences("reader",MODE_PRIVATE);loadCache();shell();if(configured())sync();else settings();}
 private boolean configured(){return !prefs.getString("server","").isEmpty();}
 private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
 private TextView text(String s,int size){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(INK);t.setPadding(0,dp(6),0,dp(6));return t;}
 private Button button(String title,Runnable action){Button b=new Button(this);b.setText(title);b.setTextColor(GREEN);b.setAllCaps(false);b.setOnClickListener(v->action.run());return b;}
 private void shell(){root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(BG);root.setPadding(dp(16),dp(12),dp(16),dp(8));setContentView(root);
  LinearLayout head=new LinearLayout(this);TextView brand=text("研迹  ResearchDock",23);head.addView(brand,new LinearLayout.LayoutParams(0,-2,1));head.addView(button("设置",()->settings()));root.addView(head);
  status=text("尚未同步；可配置自己的私有服务",11);root.addView(status);
  LinearLayout controls=new LinearLayout(this);search=new EditText(this);search.setSingleLine(true);search.setTextSize(14);search.setHint("搜索公司、行业、标题");controls.addView(search,new LinearLayout.LayoutParams(0,-2,1));controls.addView(button("同步",()->sync()));root.addView(controls);
  search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int c,int f){}public void onTextChanged(CharSequence s,int a,int b,int c){query=s.toString();render();}public void afterTextChanged(Editable e){}});
  ScrollView scroll=new ScrollView(this);content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);scroll.addView(content);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
  nav=new LinearLayout(this);for(String name:new String[]{"动态","行业","公司","收藏"})nav.addView(button(name,()->{tab=name;industry="全部";company="";render();}),new LinearLayout.LayoutParams(0,-2,1));root.addView(nav);render();
 }
 private void render(){if(content==null)return;content.removeAllViews();content.addView(text(company.isEmpty()?tab:company+" · 调研时间线",24));
  if(tab.equals("行业")&&industry.equals("全部")){TreeSet<String> names=new TreeSet<>();for(int i=0;i<docs.length();i++){JSONArray a=docs.optJSONObject(i).optJSONArray("industries");if(a!=null)for(int j=0;j<a.length();j++)names.add(a.optString(j));}for(String n:names)content.addView(button(n,()->{industry=n;render();}));if(names.isEmpty())content.addView(text("尚无行业分类；未分析原文仍可在动态阅读。",14));return;}
  if(tab.equals("公司")&&company.isEmpty()){TreeSet<String> names=new TreeSet<>();for(int i=0;i<docs.length();i++){JSONArray a=docs.optJSONObject(i).optJSONArray("companies");if(a!=null)for(int j=0;j<a.length();j++)names.add(a.optString(j));}for(String n:names)if(query.isEmpty()||n.contains(query))content.addView(button(n,()->{company=n;render();}));if(names.isEmpty())content.addView(text("尚无已关联公司；可先在 Mac 确认公司名称。",14));return;}
  if(!industry.equals("全部"))content.addView(button("← 全部行业 · "+industry,()->{industry="全部";render();}));
  if(!company.isEmpty())content.addView(button("← 公司列表",()->{company="";render();}));int count=0;
  for(int i=0;i<docs.length();i++){JSONObject d=docs.optJSONObject(i);String id=d.optString("document_id");if(tab.equals("收藏")&&!prefs.getBoolean("star:"+id,false))continue;
   if(!industry.equals("全部")&&!contains(d.optJSONArray("industries"),industry))continue;if(!company.isEmpty()&&!contains(d.optJSONArray("companies"),company))continue;
   if(!query.isEmpty()&&!(d.optString("title")+d.optString("summary")+d.optString("companies")+d.optString("industries")).contains(query))continue;
   LinearLayout card=new LinearLayout(this);card.setOrientation(LinearLayout.VERTICAL);card.setBackgroundColor(Color.WHITE);card.setPadding(dp(13),dp(9),dp(13),dp(12));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,dp(8),0,dp(8));content.addView(card,lp);
   TextView title=text(d.optString("title"),18);card.addView(title);String summary=d.optString("summary");if(!summary.isEmpty())card.addView(text(summary,13));card.addView(text(d.optString("published_at")+" · "+d.optString("source_name")+(prefs.getBoolean("read:"+id,false)?" · 已读":""),11));
   card.setOnClickListener(v->open(d));count++;
  }if(count==0)content.addView(text(configured()?"暂无符合条件的资料。先在 Mac 同步，或调整筛选。":"请先设置私有服务地址和设备阅读凭据。",15));
 }
 private boolean contains(JSONArray values,String value){if(values==null)return false;for(int i=0;i<values.length();i++)if(values.optString(i).equals(value))return true;return false;}
 private void open(JSONObject d){if(syncing)return;String id=d.optString("document_id");prefs.edit().putBoolean("read:"+id,true).apply();
  try{File f=new File(getFilesDir(),id+".json");if(f.isFile()){JSONObject cached=new JSONObject(read(f));if(cached.optInt("revision")==d.optInt("revision")&&cached.optLong("sequence")==d.optLong("sequence")){showArticle(cached);return;}}}catch(Exception ignored){}
  syncing=true;status.setText("正在读取正文…");worker.execute(()->{try{JSONObject full=request("GET","/v1/documents/"+id,null);write(new File(getFilesDir(),id+".json"),full.toString());runOnUiThread(()->showArticle(full));}catch(Exception e){runOnUiThread(()->{status.setText("正文尚未缓存或网络不可用，联网后打开一次即可离线阅读。");render();});}finally{syncing=false;}});
 }
 private void showArticle(JSONObject d){content.removeAllViews();String id=d.optString("document_id");content.addView(button("← 返回列表",()->render()));content.addView(text(d.optString("title"),24));content.addView(text(d.optString("published_at")+" · "+d.optString("source_name")+" · r"+d.optInt("revision"),12));
  content.addView(button(prefs.getBoolean("star:"+id,false)?"★ 已收藏（点击取消）":"☆ 收藏",()->{prefs.edit().putBoolean("star:"+id,!prefs.getBoolean("star:"+id,false)).apply();showArticle(d);}));
  if(!d.optString("summary").isEmpty()){content.addView(text("摘要",18));content.addView(text(d.optString("summary"),15));}content.addView(text("归档原文",18));TextView body=text(d.optString("body"),16);body.setTextIsSelectable(true);body.setLineSpacing(dp(5),1.15f);content.addView(body);status.setText("已缓存正文，可离线阅读；手机不调用模型");
 }
 private void sync(){if(!configured()){settings();return;}if(syncing)return;syncing=true;status.setText("正在同步资料列表…");worker.execute(()->{try{
  JSONArray all=new JSONArray();int offset=0;while(true){JSONObject page=request("GET","/v1/documents?limit=100&offset="+offset,null);JSONArray items=page.getJSONArray("documents");for(int i=0;i<items.length();i++)all.put(items.getJSONObject(i));offset+=items.length();if(!page.optBoolean("has_more"))break;if(offset>50000)throw new IOException("library too large");}
  write(new File(getFilesDir(),"catalog.json"),all.toString());JSONArray result=all;String stamp=new java.text.SimpleDateFormat("MM-dd HH:mm",Locale.CHINA).format(new Date());prefs.edit().putString("last_sync",stamp).apply();runOnUiThread(()->{docs=result;status.setText("已同步 "+docs.length()+" 篇 · "+stamp+"；已打开正文可离线阅读");render();});
 }catch(Exception e){runOnUiThread(()->status.setText("同步失败：请检查 HTTPS 地址、阅读凭据和网络；保留已有缓存。"));}finally{syncing=false;}});}
 private JSONObject request(String method,String path,JSONObject body)throws Exception{String server=prefs.getString("server","");URL url=new URL(server+path);if(!url.getProtocol().equals("https"))throw new IOException("HTTPS required");HttpsURLConnection conn=(HttpsURLConnection)url.openConnection();conn.setInstanceFollowRedirects(false);conn.setConnectTimeout(15000);conn.setReadTimeout(25000);conn.setRequestMethod(method);conn.setRequestProperty("Authorization","Bearer "+decrypt(prefs.getString("credential","")));try{if(body!=null){conn.setDoOutput(true);conn.setRequestProperty("Content-Type","application/json");try(OutputStream out=conn.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}}if(conn.getResponseCode()!=200)throw new IOException("request rejected");try(InputStream in=conn.getInputStream()){ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[8192];int n;while((n=in.read(buf))!=-1){if(out.size()+n>8_000_000)throw new IOException("response too large");out.write(buf,0,n);}return new JSONObject(out.toString("UTF-8"));}}finally{conn.disconnect();}}
 private void settings(){if(syncing){Toast.makeText(this,"请等待当前同步完成后再修改连接",Toast.LENGTH_SHORT).show();return;}LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(20),0,dp(20),0);EditText server=new EditText(this);server.setHint("https://你的私有阅读服务");server.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);server.setText(prefs.getString("server",""));box.addView(server);EditText token=new EditText(this);token.setHint("设备阅读凭据（留空保留）");token.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);box.addView(token);box.addView(text("凭据经 Android Keystore 加密保存。请勿填入 DeepSeek Key 或星球登录凭据。收藏和已读目前只存于此手机。",12));
  AlertDialog dialog=new AlertDialog.Builder(this).setTitle("连接私有阅读服务").setView(box).setNegativeButton("取消",null).setPositiveButton("保存并同步",null).create();dialog.setOnShowListener(x->dialog.getButton(-1).setOnClickListener(v->{try{String s=server.getText().toString().trim().replaceAll("/+$","");URI uri=new URI(s);if(!"https".equals(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null||uri.getPath().contains(".."))throw new Exception();String old=prefs.getString("server","");String t=token.getText().toString().trim();if(!t.isEmpty()&&t.length()<32)throw new Exception();if(t.isEmpty()&&(!old.equals(s)||prefs.getString("credential","").isEmpty()))throw new Exception();if(!old.equals(s)){docs=new JSONArray();for(File f:getFilesDir().listFiles())if(f.getName().endsWith(".json"))f.delete();prefs.edit().clear().apply();}android.content.SharedPreferences.Editor edit=prefs.edit().putString("server",s);if(!t.isEmpty()){if(t.length()<32)throw new Exception();edit.putString("credential",encrypt(t));}edit.apply();dialog.dismiss();sync();}catch(Exception e){Toast.makeText(this,"请输入有效 HTTPS 根地址与至少32字符的阅读凭据",Toast.LENGTH_LONG).show();}}));dialog.show();}
 private javax.crypto.SecretKey secret()throws Exception{KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);if(!ks.containsAlias("reader-token")){KeyGenerator generator=KeyGenerator.getInstance("AES","AndroidKeyStore");generator.init(new KeyGenParameterSpec.Builder("reader-token",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());return generator.generateKey();}return (javax.crypto.SecretKey)ks.getKey("reader-token",null);}
 private String encrypt(String value)throws Exception{Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,secret());return Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+":"+Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);}
 private String decrypt(String value)throws Exception{String[] parts=value.split(":",2);Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,secret(),new GCMParameterSpec(128,Base64.decode(parts[0],Base64.NO_WRAP)));return new String(cipher.doFinal(Base64.decode(parts[1],Base64.NO_WRAP)),StandardCharsets.UTF_8);}
 private void loadCache(){try{docs=new JSONArray(read(new File(getFilesDir(),"catalog.json")));}catch(Exception ignored){}}
 private String read(File f)throws Exception{try(InputStream in=new FileInputStream(f)){ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);return out.toString("UTF-8");}}
 private synchronized void write(File f,String text)throws Exception{File tmp=new File(f.getPath()+".tmp");try(FileOutputStream out=new FileOutputStream(tmp)){out.write(text.getBytes(StandardCharsets.UTF_8));out.getFD().sync();}if(!tmp.renameTo(f))throw new IOException("cache write failed");}
 @Override protected void onDestroy(){worker.shutdown();super.onDestroy();}
}
