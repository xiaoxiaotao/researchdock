package org.researchdock.mobile;
import android.app.*;import android.content.*;import android.view.*;import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;import org.junit.Test;import static org.junit.Assert.*;
public class ResearchAssistantTest {
 private String text(View v){StringBuilder s=new StringBuilder();if(v instanceof TextView)s.append(((TextView)v).getText()).append('\n');if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)s.append(text(((ViewGroup)v).getChildAt(i)));return s.toString();}
 private Object field(ResearchActivity a,String name)throws Exception{java.lang.reflect.Field f=ResearchActivity.class.getDeclaredField(name);f.setAccessible(true);return f.get(a);}
 @Test public void formReportAndCitationsKeepEvidenceAndCoverageVisible()throws Exception{
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("navigation_test")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();ResearchActivity a=(ResearchActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),ResearchActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
  try{inst.runOnMainSync(()->{try{View view=a.getWindow().getDecorView();assertTrue(text(view).contains("从已有资料"));assertNotNull(view.findViewWithTag("research:question"));assertNotNull(view.findViewWithTag("research:submit"));assertTrue(text(view).contains("PDF、图片和音频不自动解析"));
   java.lang.reflect.Field task=ResearchActivity.class.getDeclaredField("taskId");task.setAccessible(true);task.set(a,"a".repeat(32));
   JSONObject report=new JSONObject().put("target","合成公司").put("kind","company").put("days",30).put("model","测试模型").put("scope",new JSONObject().put("selected_documents",2).put("matched_documents",4).put("attachment_documents",1).put("truncated",true)).put("evidence",new JSONArray().put(new JSONObject().put("id","E1").put("title","原文证据样例").put("quote","合成原文摘录，不是真实研报").put("revision",2))).put("sections",new JSONArray().put(new JSONObject().put("title","结论摘要").put("items",new JSONArray().put(new JSONObject().put("text","**已有证据**中的判断").put("citations",new JSONArray().put("E1"))))));
   JSONObject data=new JSONObject().put("id","a".repeat(32)).put("question","合成研究，不调用模型").put("status","completed").put("report",report);
   java.lang.reflect.Method render=ResearchActivity.class.getDeclaredMethod("renderReport",JSONObject.class,boolean.class);render.setAccessible(true);render.invoke(a,data,true);String shown=text(view);assertTrue(shown.contains("原文证据样例"));assertTrue(shown.contains("未解析附件 1"));assertTrue(shown.contains("仅选取相关正文摘录"));assertTrue(shown.contains("结论摘要"));assertTrue(shown.contains("继续追问"));assertTrue(shown.contains("离线报告"));
  }catch(Exception e){throw new RuntimeException(e);}});
  }finally{inst.runOnMainSync(a::finish);}
 }
}
