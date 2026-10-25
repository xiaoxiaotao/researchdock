package org.researchdock.mobile;
import android.app.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.Bundle;
import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.json.*;
import static org.junit.Assert.*;

/** Same harness can run against the previous signed APK for controlled comparison. */
public class PerformanceReadingTest {
 private Object get(MainActivity a,String key)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(key);f.setAccessible(true);return f.get(a);}
 private void set(MainActivity a,String key,Object value)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(key);f.setAccessible(true);f.set(a,value);}
 private void call(MainActivity a,String method)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod(method);m.setAccessible(true);m.invoke(a);}
 private void article(MainActivity a,JSONObject d)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod("showArticle",JSONObject.class);m.setAccessible(true);m.invoke(a,d);}
 @Test public void controlledReadingAndCompanyProbe()throws Exception{
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("performance_probe")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();MainActivity a=(MainActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
  SharedPreferences prefs=a.getSharedPreferences("reader",Context.MODE_PRIVATE);String previous=prefs.getString("last_article","");JSONObject result=new JSONObject();JSONArray companyTimes=new JSONArray();
  try{
   result.put("version",a.getPackageManager().getPackageInfo(a.getPackageName(),0).versionName);result.put("documents",((JSONArray)get(a,"docs")).length());
   for(int attempt=0;attempt<3;attempt++){final long[] elapsed={0};inst.runOnMainSync(()->{try{set(a,"tab","公司");long t=System.nanoTime();call(a,"render");elapsed[0]=System.nanoTime()-t;}catch(Exception e){throw new RuntimeException(e);}});companyTimes.put(elapsed[0]/1000000.0);inst.waitForIdleSync();Thread.sleep(100);}
   result.put("company_handler_ms",companyTimes);
   StringBuilder body=new StringBuilder("# 长文性能验证样例\n\n");for(int i=0;i<450;i++){if(i%30==0)body.append("## 章节 ").append(i/30+1).append("\n");body.append("第").append(i).append("段：营业收入 **100万元**、净利润 -5万元，这是用于测试原生排版的合成数字。保留正文、来源和证据，避免因为排版遗漏研究内容。阅读操作应保持可响应，段落之间具有清晰的层次。\n\n");}
   JSONObject d=new JSONObject();d.put("document_id","performance-probe");d.put("revision",1);d.put("title","长文性能验证样例，不是真实研报");d.put("body",body.toString());result.put("article_characters",body.length());final long[] open={0};long completeStart=System.nanoTime();
   inst.runOnMainSync(()->{try{long t=System.nanoTime();article(a,d);open[0]=System.nanoTime()-t;}catch(Exception e){throw new RuntimeException(e);}});
   long deadline=System.currentTimeMillis()+15000;while(true){final boolean[] pending={false};inst.runOnMainSync(()->{try{pending[0]=(Boolean)get(a,"articleRenderPending");}catch(NoSuchFieldException oldVersion){pending[0]=false;}catch(Exception e){throw new RuntimeException(e);}});if(!pending[0])break;assertTrue("Long article must complete",System.currentTimeMillis()<deadline);Thread.sleep(20);}
   result.put("article_open_handler_ms",open[0]/1000000.0);result.put("article_completion_ms",(System.nanoTime()-completeStart)/1000000.0);
   inst.waitForIdleSync();inst.runOnMainSync(()->{try{call(a,"returnToList");}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();
   // Cancelling a partial render must not repopulate the restored list.
   final Object[] list={null};inst.runOnMainSync(()->{try{list[0]=get(a,"content");article(a,d);call(a,"returnToList");}catch(Exception e){throw new RuntimeException(e);}});Thread.sleep(350);inst.runOnMainSync(()->{try{assertSame(list[0],get(a,"content"));assertFalse((Boolean)get(a,"reading"));}catch(Exception e){throw new RuntimeException(e);}});result.put("cancel_returns_original_list",true);
   Drawable icon=a.getPackageManager().getApplicationIcon(a.getPackageName());result.put("custom_icon",a.getApplicationInfo().icon!=0);Bitmap bitmap=Bitmap.createBitmap(384,384,Bitmap.Config.ARGB_8888);icon.setBounds(0,0,384,384);icon.draw(new Canvas(bitmap));try(java.io.FileOutputStream out=new java.io.FileOutputStream(new java.io.File(a.getFilesDir(),"launcher-icon-preview.png"))){bitmap.compress(Bitmap.CompressFormat.PNG,100,out);}
   try(java.io.FileOutputStream out=new java.io.FileOutputStream(new java.io.File(a.getFilesDir(),"performance-probe.json"))){out.write(result.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));}
   Bundle report=new Bundle();report.putString("stream",result.toString()+"\n");inst.sendStatus(0,report);
  }finally{inst.runOnMainSync(()->{try{if((Boolean)get(a,"reading"))call(a,"returnToList");}catch(Exception e){throw new RuntimeException(e);}prefs.edit().putString("last_article",previous).remove("progress:performance-probe:r1").apply();a.finish();});}
 }
}
