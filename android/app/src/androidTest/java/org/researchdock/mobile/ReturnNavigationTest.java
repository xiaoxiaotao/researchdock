package org.researchdock.mobile;
import android.app.*;
import android.content.*;
import android.view.*;
import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.json.JSONObject;
import static org.junit.Assert.*;

public class ReturnNavigationTest {
 private Object get(Object object,String key)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(key);f.setAccessible(true);return f.get(object);}
 private void set(Object object,String key,Object value)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(key);f.setAccessible(true);f.set(object,value);}
 private void call(Object object,String method)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod(method);m.setAccessible(true);m.invoke(object);}
 private void article(Object object,JSONObject d)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod("showArticle",JSONObject.class);m.setAccessible(true);m.invoke(object,d);}
 private Button find(View v,String title){if(v instanceof Button&&((Button)v).getText().toString().equals(title))return (Button)v;if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++){Button b=find(((ViewGroup)v).getChildAt(i),title);if(b!=null)return b;}return null;}
 @Test public void toolbarAndSystemBackRetainListAndLoadedPages() throws Exception {
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("navigation_test")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();MainActivity activity=(MainActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
  SharedPreferences prefs=activity.getSharedPreferences("reader",Context.MODE_PRIVATE);String previous=prefs.getString("last_article","");
  JSONObject d=new JSONObject();d.put("document_id","navigation-regression");d.put("revision",1);d.put("title","临时导航验证，不写入资料库");d.put("body","# 标题\n用于验证列表返回位置。");
  final Object[] list={null};final int[] y={0};
  try{
   inst.runOnMainSync(()->{try{set(activity,"tab","动态");set(activity,"listLimit",120);call(activity,"render");}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();Thread.sleep(200);
   inst.runOnMainSync(()->{try{ScrollView scroll=(ScrollView)get(activity,"scroll");scroll.scrollTo(0,1800);y[0]=scroll.getScrollY();assertTrue(y[0]>500);list[0]=get(activity,"content");article(activity,d);}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();Thread.sleep(300);
   inst.runOnMainSync(()->{try{assertNotSame(list[0],get(activity,"content"));Button back=find((View)get(activity,"root"),"‹ 返回");assertNotNull(back);back.performClick();}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();Thread.sleep(150);
   inst.runOnMainSync(()->{try{assertSame(list[0],get(activity,"content"));assertEquals(y[0],((ScrollView)get(activity,"scroll")).getScrollY(),3);assertEquals(120,get(activity,"listLimit"));article(activity,d);article(activity,d);activity.onBackPressed();}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();Thread.sleep(150);
   inst.runOnMainSync(()->{try{assertSame(list[0],get(activity,"content"));assertEquals(y[0],((ScrollView)get(activity,"scroll")).getScrollY(),3);assertFalse((Boolean)get(activity,"reading"));}catch(Exception e){throw new RuntimeException(e);}});
  }finally{inst.runOnMainSync(()->{try{if((Boolean)get(activity,"reading"))activity.onBackPressed();}catch(Exception e){throw new RuntimeException(e);}prefs.edit().putString("last_article",previous).remove("progress:navigation-regression:r1").apply();activity.finish();});}
 }
}
