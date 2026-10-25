package org.researchdock.mobile;
import org.json.JSONObject;
import java.time.*;
import java.util.Locale;

/** Deterministic metadata filters: no ranking service, model or financial inference. */
final class LibraryViews {
 static String day(JSONObject d){String value=d.optString("published_at");return value.length()>=10?value.substring(0,10):"日期未知";}
 static String date(String value){String v=value.replace('T',' ');return v.length()>=16?v.substring(0,16):v;}
 static String progressKey(JSONObject d){return "progress:"+d.optString("document_id")+":r"+d.optInt("revision");}
 static boolean matches(JSONObject d,String query,String source,int days,String mode,boolean opened,boolean followed,float progress,LocalDate today){
  if(!source.isEmpty()&&!source.equals(d.optString("source_name")))return false;
  if(days>0){try{LocalDate date=LocalDate.parse(day(d));if(date.isBefore(today.minusDays(days-1))||date.isAfter(today))return false;}catch(Exception e){return false;}}
  if(mode.equals("未读")&&opened||mode.equals("关注")&&!followed||mode.equals("续读")&&(progress<=0.02f||progress>=0.98f))return false;
  String normalized=query.trim().toLowerCase(Locale.ROOT);
  return normalized.isEmpty()||(d.optString("title")+" "+d.optString("summary")+" "+d.optString("companies")+" "+d.optString("company_securities")+" "+d.optString("industries")).toLowerCase(Locale.ROOT).contains(normalized);
 }
}
