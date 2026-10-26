package org.researchdock.mobile;
import android.app.*;import android.content.*;import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;import org.junit.Test;import static org.junit.Assert.*;
public class ArticleLoadingTest {
 private Object get(MainActivity a,String k)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(k);f.setAccessible(true);return f.get(a);}
 private void set(MainActivity a,String k,Object v)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(k);f.setAccessible(true);f.set(a,v);}
 private void open(MainActivity a,JSONObject d)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod("open",JSONObject.class);m.setAccessible(true);m.invoke(a,d);}
 @Test public void failedOpenKeepsUnreadAndCacheOpensDuringCatalogSync()throws Exception{
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("navigation_test")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();MainActivity a=(MainActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
  for(int n=0;n<300&&(Boolean)get(a,"syncing");n++)Thread.sleep(100);assertFalse((Boolean)get(a,"syncing"));
  SharedPreferences p=a.getSharedPreferences("reader",Context.MODE_PRIVATE);String server=p.getString("server",""),last=p.getString("last_article","");String id="loading-regression";java.io.File cache=new java.io.File(a.getFilesDir(),id+".json");JSONObject d=new JSONObject().put("document_id",id).put("revision",1).put("title","加载验证，合成资料");
  try{
   p.edit().putString("server","https://127.0.0.1:1").remove("read:"+id).commit();cache.delete();
   inst.runOnMainSync(()->{try{open(a,d);assertFalse(p.getBoolean("read:"+id,false));}catch(Exception e){throw new RuntimeException(e);}});
   boolean failed=false;for(int n=0;n<100;n++){String[] text={""};inst.runOnMainSync(()->{try{text[0]=((TextView)get(a,"status")).getText().toString();}catch(Exception e){throw new RuntimeException(e);}});if(text[0].contains("正文尚未缓存")){failed=true;break;}Thread.sleep(100);}assertTrue(failed);assertFalse(p.getBoolean("read:"+id,false));assertFalse((Boolean)get(a,"reading"));
   java.nio.file.Files.write(cache.toPath(),new JSONObject(d.toString()).put("body","# 合成标题\n已缓存正文，读取失败不应误标已读。").toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
   inst.runOnMainSync(()->{try{set(a,"syncing",true);open(a,d);}catch(Exception e){throw new RuntimeException(e);}});
   for(int n=0;n<100&&!p.getBoolean("read:"+id,false);n++)Thread.sleep(50);inst.waitForIdleSync();assertTrue(p.getBoolean("read:"+id,false));assertTrue((Boolean)get(a,"reading"));assertEquals(id,((JSONObject)get(a,"currentArticle")).getString("document_id"));
  }finally{inst.runOnMainSync(()->{try{set(a,"syncing",false);if((Boolean)get(a,"reading"))a.onBackPressed();}catch(Exception e){throw new RuntimeException(e);}p.edit().putString("server",server).putString("last_article",last).remove("read:"+id).remove("progress:"+id+":r1").commit();a.finish();});cache.delete();}
 }
}
